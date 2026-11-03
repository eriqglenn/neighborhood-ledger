#!/usr/bin/env python3
"""Neighborhood Ledger local companion service.

Serves the selected community and retrieves a limited set of approved public sources:
- City of Houston Plat Activity Reports
- City of Houston Permit E-Report
- City of Houston / ArcGIS Super Neighborhood boundary
- Houston Open Data catalog
- ArcGIS public catalog search
- Grants.gov opportunity APIs

The service binds to 127.0.0.1 only and is not a general-purpose proxy.
"""
from __future__ import annotations
from communities import profile, label
import contextvars
from concurrent.futures import ThreadPoolExecutor

import datetime as dt
import html as html_lib
import io
import json
import math
import mimetypes
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from paths import APP_DIR, data_dir
from geography import select_feature, validate_feature, contains, precise_address

HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "neighborops.html"
CACHE_FILE = data_dir() / "geography-cache.json"
USER_AGENT = "Neighborhood-Ledger/13.6 (public civic data client)"

PLAT_REPORT_PAGE = "https://www.houstontx.gov/planning/DevelopRegs/dev_reports.html"
PLAT_FALLBACK = "https://www.houstontx.gov/planning/DevelopRegs/docs_pdfs/Plat_report/2026/Plat-Current-Agenda-Spreadsheet-07-09-2026.xlsx"
PLAT_LOCAL_CACHE = ROOT / "plat_cache_2026-07-09.xlsx"
PERMIT_REPORT = "https://houstontx.gov/planning/Publications/listsrv/WebeReport.html"
GRANTS_SEARCH = "https://api.grants.gov/v1/api/search2"
GRANTS_DETAIL = "https://api.grants.gov/v1/api/fetchOpportunity"
HOUSTON_CKAN = "https://data.houstontx.gov/api/3/action/package_search"
ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"
ARCGIS_ITEM = "71e2745273644d61bda82d04c44eb600"
ARCGIS_ITEM_META = f"https://www.arcgis.com/sharing/rest/content/items/{ARCGIS_ITEM}"
ARCGIS_GEOCODER = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
FALLBACK_BOUNDARY_SERVICE = "https://mapsop1.houstontx.gov/arcgis/rest/services/CAS/CASMapViewer/MapServer/3/query"

LIKELY_ZIPS = {"77020", "77026"}

SSL_CONTEXT = ssl.create_default_context()


def load_cache() -> dict[str, Any]:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"geocodes": {}, "boundary": None, "boundary_time": 0}


def save_cache(cache: dict[str, Any]) -> None:
    temporary = CACHE_FILE.with_suffix('.tmp')
    with CACHE_LOCK:
        temporary.write_text(json.dumps(cache, indent=2), encoding='utf-8')
        temporary.replace(CACHE_FILE)

CACHE_LOCK = threading.RLock()


CACHE = load_cache()


def request_bytes(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 35) -> bytes:
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace")
        raise RuntimeError(f"Remote source returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach remote source: {exc.reason}") from exc


def request_text(url: str, *, timeout: int = 35) -> str:
    data = request_bytes(url, timeout=timeout)
    for encoding in ("utf-8", "windows-1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def request_json(url: str, *, payload: dict[str, Any] | None = None, timeout: int = 35) -> dict[str, Any]:
    if payload is None:
        raw = request_bytes(url, timeout=timeout)
    else:
        raw = request_bytes(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=timeout,
        )
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Remote source returned invalid JSON") from exc


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html_lib.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_key(record: dict[str, Any], *candidates: str) -> Any:
    normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in record.items()}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        if key in normalized:
            return normalized[key]
    for candidate in candidates:
        needle = re.sub(r"[^a-z0-9]", "", candidate.lower())
        for key, value in normalized.items():
            if needle and needle in key:
                return value
    return ""


# ---------------------------- XLSX parser ----------------------------

def col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return 0
    n = 0
    for char in letters.group(0):
        n = n * 26 + ord(char) - 64
    return n - 1


def xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    result = []
    for si in root.findall("m:si", ns):
        result.append("".join(t.text or "" for t in si.findall(".//m:t", ns)))
    return result


def xlsx_first_sheet_path(zf: zipfile.ZipFile) -> str:
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        first = workbook.find("m:sheets/m:sheet", ns)
        rel_id = first.attrib.get(f"{{{ns['r']}}}id") if first is not None else None
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.findall("p:Relationship", ns):
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib.get("Target", "worksheets/sheet1.xml").lstrip("/")
                return target if target.startswith("xl/") else "xl/" + target
    except Exception:
        pass
    return "xl/worksheets/sheet1.xml"


def parse_xlsx_rows(content: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared = xlsx_shared_strings(zf)
        sheet_path = xlsx_first_sheet_path(zf)
        root = ET.fromstring(zf.read(sheet_path))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    matrix: list[list[Any]] = []
    for row in root.findall(".//m:sheetData/m:row", ns):
        values: dict[int, Any] = {}
        max_col = -1
        for cell in row.findall("m:c", ns):
            idx = col_index(cell.attrib.get("r", ""))
            max_col = max(max_col, idx)
            ctype = cell.attrib.get("t", "")
            if ctype == "inlineStr":
                value = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
            else:
                v = cell.find("m:v", ns)
                value = v.text if v is not None else ""
                if ctype == "s" and value:
                    try:
                        value = shared[int(value)]
                    except Exception:
                        pass
                elif ctype == "b":
                    value = value == "1"
            values[idx] = value
        if max_col >= 0:
            matrix.append([values.get(i, "") for i in range(max_col + 1)])
    header_idx = None
    for i, row in enumerate(matrix[:30]):
        normalized = [clean_text(x).lower() for x in row]
        if any("super neighborhood" in x for x in normalized) and any("app" in x and "no" in x for x in normalized):
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("Could not find the Plat Activity Report header row")
    headers = [clean_text(x) or f"Column {i+1}" for i, x in enumerate(matrix[header_idx])]
    records = []
    for row in matrix[header_idx + 1 :]:
        if not any(clean_text(v) for v in row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        records.append({headers[i]: padded[i] for i in range(len(headers))})
    return records


def excel_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return "Not provided"
    try:
        serial = float(text)
        if 30000 < serial < 70000:
            date = dt.datetime(1899, 12, 30) + dt.timedelta(days=serial)
            return date.strftime("%Y-%m-%d")
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return text


def discover_plat_url() -> str:
    try:
        page = request_text(PLAT_REPORT_PAGE)
        links = re.findall(r'href=["\']([^"\']+\.xlsx(?:\?[^"\']*)?)["\']', page, re.I)
        candidates = []
        for link in links:
            url = urllib.parse.urljoin(PLAT_REPORT_PAGE, html_lib.unescape(link))
            if "Plat-Current-Agenda-Spreadsheet" not in url:
                continue
            match = re.search(r"(\d{2})-(\d{2})-(\d{4})", url)
            score = dt.date(int(match.group(3)), int(match.group(1)), int(match.group(2))) if match else dt.date.min
            candidates.append((score, url))
        if candidates:
            return max(candidates, key=lambda x: x[0])[1]
    except Exception:
        pass
    return PLAT_FALLBACK


def scan_plats() -> dict[str, Any]:
    from plat_service import scan_plats as reliable_scan
    return reliable_scan(root=data_dir())


# ---------------------------- HTML tables ----------------------------
class TableRowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self.current_row = []
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = []
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_row.append(clean_text("".join(self.current_cell)))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if any(self.current_row):
                self.rows.append(self.current_row)
            self.current_row = None


def parse_permit_rows(page: str) -> list[dict[str, str]]:
    parser = TableRowsParser()
    parser.feed(page)
    results = []
    for cells in parser.rows:
        cells = [clean_text(c) for c in cells]
        if len(cells) < 6:
            continue
        zip_idx = next((i for i, c in enumerate(cells) if re.fullmatch(r"77\d{3}", c)), None)
        if zip_idx is None or zip_idx + 5 >= len(cells):
            continue
        date, permit_type, project, address, description = cells[zip_idx + 1 : zip_idx + 6]
        if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", date) or not re.fullmatch(r"\d{7,}", project):
            continue
        results.append({"zip": cells[zip_idx], "date": date.replace("/", "-"), "type": permit_type, "project": project, "address": address, "description": description})
    return results


def significant_permit(record: dict[str, str]) -> bool:
    text = f"{record.get('type', '')} {record.get('description', '')}".lower()
    if re.search(r"re-?roof|swimming pool|solar panel|minor residential repair|foundation repair|generator replacement|elevator replacement", text):
        return False
    return bool(re.search(r"\bnew\b|demolition|\bdemo\b|change.?of.?use|commercial|multifamily|multi-family|apartment|duplex|townhome|townhouse|warehouse|retail|restaurant|office|clinic|school|community|addition|shell|site work|parking lot|industrial", text))


# ---------------------------- Boundary / geocoding ----------------------------
def find_fifth_ward_feature(geo):
    return select_feature(geo)


def get_boundary(force: bool = False) -> dict[str, Any]:
    cache_key = "boundary:" + profile()["id"]
    cached = CACHE.get(cache_key)
    cached_time = float(CACHE.get(cache_key + ":time") or 0)
    if cached and not force and time.time() - cached_time < 7 * 86400:
        try:
            return validate_feature(cached)
        except ValueError:
            pass
    feature = None
    errors = []
    try:
        meta_url = ARCGIS_ITEM_META + "?" + urllib.parse.urlencode({"f": "json"})
        meta = request_json(meta_url)
        service_url = meta.get("url")
        if service_url:
            service = request_json(service_url + "?f=json")
            layers = service.get("layers") or []
            layer = next((x for x in layers if re.search(r"super.*neigh", str(x.get("name", "")), re.I)), None)
            if layer is None: raise RuntimeError("Official neighborhood layer was not identified")
            query_url = f"{service_url.rstrip('/')}/{layer.get('id', 0)}/query?" + urllib.parse.urlencode({"where": "POLYID=" + profile()["id"], "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson"})
            feature = find_fifth_ward_feature(request_json(query_url, timeout=50))
    except Exception as exc:
        errors.append(str(exc))
    if not feature:
        try:
            query_url = FALLBACK_BOUNDARY_SERVICE + "?" + urllib.parse.urlencode({"where": "POLYID=" + profile()["id"], "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson"})
            feature = find_fifth_ward_feature(request_json(query_url, timeout=50))
        except Exception as exc:
            errors.append(str(exc))
    if not feature:
        raise RuntimeError("Official " + label() + " boundary could not be retrieved. Permit scan stopped; no ZIP-only fallback was used. " + " | ".join(errors[-2:]))
    if "attributes" in feature and "properties" not in feature:
        feature["properties"] = feature.pop("attributes")
    validate_feature(feature)
    feature["properties"]["ledgerSourceUrl"] = query_url
    feature["properties"]["ledgerCheckedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    CACHE[cache_key] = feature
    CACHE[cache_key + ":time"] = time.time()
    save_cache(CACHE)
    return feature


def ring_contains(point: tuple[float, float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_feature(lng, lat, feature):
    return contains(lng, lat, feature)


def geocode(address,zip_code=None):
    if zip_code is not None and not re.fullmatch(r'77\d{3}',zip_code):raise ValueError('Invalid Houston-area report ZIP')
    key = clean_text(address).upper()+(' | '+zip_code if zip_code else '')
    cached = CACHE.setdefault('geocodes', {}).get(key)
    if cached and cached.get('policy') == 'precise-address-v3' and time.time()-cached.get('checkedEpoch',0)<30*86400:
        return cached
    url = ARCGIS_GEOCODER + '?' + urllib.parse.urlencode({'f':'json','maxLocations':3,'outFields':'Match_addr,Addr_type,AddNum,StName,StPreDir,StDir,StType,City,Postal','outSR':4326,'SingleLine':address+(', TX '+zip_code if zip_code else ', Houston, TX')})
    candidates = request_json(url, timeout=10).get('candidates') or []
    matches = [c for c in candidates if precise_address(c,address,zip_code)]
    if not matches: raise RuntimeError('No precise address match in the requested Houston-area location at score 95 or higher; location remains unverified')
    candidate = matches[0]
    if any(abs(c['location']['x']-candidate['location']['x'])>0.0001 or abs(c['location']['y']-candidate['location']['y'])>0.0001 for c in matches[1:]): raise RuntimeError('Multiple precise address candidates disagree on location; manual source review required')
    result = {'lat':candidate['location']['y'],'lng':candidate['location']['x'],'match':candidate['address'],'score':candidate['score'],'addrType':candidate['attributes']['Addr_type'],'attributes':candidate['attributes'],'policy':'precise-address-v3','checkedEpoch':time.time(),'sourceUrl':ARCGIS_GEOCODER,'requestedAddress':address}
    if not (-96<float(result['lng'])<-94 and 28<float(result['lat'])<31): raise RuntimeError('Geocode coordinates are not Houston WGS84')
    with CACHE_LOCK:
        CACHE['geocodes'][key]=result
        save_cache(CACHE)
    return result


def scan_permits(page=None, source_url=PERMIT_REPORT):
    boundary = get_boundary()
    page = request_text(PERMIT_REPORT,timeout=15) if page is None else page
    import hashlib
    digest=hashlib.sha256(page.encode('utf-8')).hexdigest()
    evidence=CACHE_FILE.parent/'permit_evidence';evidence.mkdir(parents=True,exist_ok=True)
    (evidence/(digest+'.html')).write_text(page,encoding='utf-8')
    plain = clean_text(page)
    if not all(re.search(r'\b'+x+r'\b',plain,re.I) for x in ['Zip Code','Permit Date','Project No','Address']):
        raise RuntimeError('Permit report schema not recognized; this is not a zero-result scan')
    span = re.search(r'From:\s*(\d{4}/\d{2}/\d{2})\s*To\s*:\s*(\d{4}/\d{2}/\d{2})',plain,re.I)
    if not span: raise RuntimeError('Permit reporting period missing; freshness cannot be verified')
    end = dt.datetime.strptime(span[2],'%Y/%m/%d').date()
    start = dt.datetime.strptime(span[1],'%Y/%m/%d').date()
    if start>end: raise RuntimeError('Permit reporting period is reversed')
    age = (dt.date.today()-end).days
    if age<0 or age>21: raise RuntimeError('Permit report is future-dated or older than 21 days; current scan stopped')
    parsed = parse_permit_rows(page)
    candidates = [r for r in parsed if significant_permit(r)]
    accepted=[];rejected=[];deferred=[];deadline=time.monotonic()+120
    def evaluate(record):
        if time.monotonic()>deadline:
            return ('deferred',{**record,'reason':'Scan time budget reached; not evaluated'})
        try:
            record_date=dt.date.fromisoformat(record['date'])
            if not start<=record_date<=end: raise ValueError('Permit date is outside the reporting period')
            # A unit pair is not part of the street name; retain the full report address.
            street_address=re.sub(r'\s+[A-Z]\s*&\s*[A-Z]$','',record['address'].strip(),flags=re.I)
            geo=geocode(street_address,zip_code=record['zip'])
            if street_address!=record['address']:geo={**geo,'reportAddress':record['address'],'addressNormalization':'Removed trailing letter unit pair for base-building geocode'}
            if not contains(float(geo['lng']),float(geo['lat']),boundary): raise ValueError('Outside selected official boundary or on boundary edge')
            return ('accepted',{'kind':'Permit','externalKey':'permit:'+record['project'],'caseNo':record['project'],'title':record['description'],'date':record['date'],'location':geo['match'],'rawAddress':record['address'],'status':'Permit reported','activity':record['type'],'lat':geo['lat'],'lng':geo['lng'],'url':'https://www.houstonpermittingcenter.org/sold-permits-search','sourceUrl':source_url,'source':'Houston Permit E-Report','matchMethod':'Precise address and official '+label()+' polygon, holes and edges checked','summary':record['description'],'provenance':{'reportSha256':digest,'sourceUrl':source_url,'rawRow':record,'retrievedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'geocode':geo,'boundarySource':boundary['properties'].get('ledgerSourceUrl'),'boundaryCheckedAt':boundary['properties'].get('ledgerCheckedAt'),'reportStart':span[1],'reportEnd':span[2]}})
        except Exception as e:
            return ('rejected' if str(e)=='Outside selected official boundary or on boundary edge' else 'deferred',{**record,'reason':str(e)})
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs=[pool.submit(contextvars.copy_context().run,evaluate,record) for record in candidates]
        for job in jobs:
            kind,record=job.result()
            {"accepted":accepted,"rejected":rejected,"deferred":deferred}[kind].append(record)
    return {'status':'partial' if deferred else 'success','sourceMode':'live_permit_report','retrievedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'reportSha256':digest,'sourceUrl':source_url,'results':accepted,'parsedRows':len(parsed),'significantCandidates':len(candidates),'rejectedCount':len(rejected),'rejected':rejected,'deferred':deferred,'reportStart':span[1],'reportEnd':span[2],'coverage':'Significant construction in the current Houston E-Report across all reported ZIPs; filtered to '+label()+'. Not a comprehensive permit inventory','warnings':[str(len(deferred))+' candidate addresses could not be verified; see source evidence.'] if deferred else [],'strictFilter':'Precise address inside official '+label()+'; no ZIP or display-boundary acceptance'}


# ---------------------------- Grants ----------------------------
def applicant_assessment(detail: dict[str, Any]) -> tuple[str, bool]:
    synopsis = detail.get("synopsis") or {}
    labels = [clean_text(x.get("description")) for x in synopsis.get("applicantTypes") or [] if isinstance(x, dict)]
    joined = " ".join(labels).lower()
    if "unrestricted" in joined or "others" in joined:
        return "Possible direct eligibility — verify full notice", True
    if labels:
        return "Partner or eligible entity required: " + "; ".join(labels[:3]), False
    return "Eligibility requires full-notice review", False


def grant_fit(detail: dict[str, Any], query: str) -> str:
    synopsis = detail.get("synopsis") or {}
    categories = " ".join(clean_text(x.get("description")) for x in synopsis.get("fundingActivityCategories") or [] if isinstance(x, dict))
    text = f"{detail.get('opportunityTitle', '')} {synopsis.get('synopsisDesc', '')} {categories}".lower()
    priorities = ["community", "neighborhood", "housing", "resilience", "disaster", "food", "nutrition", "health", "youth", "education", "arts", "culture", "environment", "employment", "workforce", "justice", "safety", "infrastructure", "economic development"]
    score = sum(1 for word in priorities if word in text)
    if query.lower() in text:
        score += 3
    return "High" if score >= 6 else "Medium" if score >= 3 else "Low"


def scan_grants(query: str, category: str, rows: int, direct_only: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {"rows": max(rows * 3, 20), "keyword": query, "oppStatuses": "posted|forecasted"}
    if category:
        payload["fundingCategories"] = category
    try:
        search = request_json(GRANTS_SEARCH, payload=payload, timeout=50)
    except Exception:
        # Retry with the smallest broadly compatible payload.
        search = request_json(GRANTS_SEARCH, payload={"rows": max(rows * 3, 20), "keyword": query}, timeout=50)
    hits = ((search.get("data") or {}).get("oppHits") or [])
    results = []
    detail_errors = 0
    for hit in hits[: max(rows * 3, 20)]:
        opp_id = hit.get("id")
        if opp_id is None:
            continue
        try:
            detail_response = request_json(GRANTS_DETAIL, payload={"opportunityId": int(opp_id)}, timeout=40)
            detail = detail_response.get("data") or {}
        except Exception:
            detail_errors += 1
            continue
        applicant, direct = applicant_assessment(detail)
        if direct_only and not direct:
            continue
        synopsis = detail.get("synopsis") or {}
        categories = ", ".join(clean_text(x.get("description")) for x in synopsis.get("fundingActivityCategories") or [] if isinstance(x, dict))
        result = {
            "id": str(detail.get("id") or opp_id),
            "number": clean_text(detail.get("opportunityNumber")),
            "title": clean_text(detail.get("opportunityTitle")) or "Untitled opportunity",
            "agency": clean_text(synopsis.get("agencyName") or (detail.get("agencyDetails") or {}).get("agencyName")) or "Federal agency",
            "open": clean_text(synopsis.get("postingDate")),
            "close": clean_text(synopsis.get("responseDate") or synopsis.get("responseDateDesc")),
            "description": clean_text(synopsis.get("synopsisDesc"))[:700],
            "applicant": applicant,
            "direct": direct,
            "fit": grant_fit(detail, query),
            "categories": categories,
            "url": f"https://www.grants.gov/search-results-detail/{opp_id}",
        }
        results.append(result)
        if len(results) >= rows:
            break
    rank = {"High": 3, "Medium": 2, "Low": 1}
    results.sort(key=lambda x: rank.get(x["fit"], 0), reverse=True)
    return {"query": query, "count": len(results), "detailErrors": detail_errors, "results": results, "source": "Grants.gov"}


# ---------------------------- Misc APIs ----------------------------
def search_ckan(query: str, rows: int = 8) -> dict[str, Any]:
    url = HOUSTON_CKAN + "?" + urllib.parse.urlencode({"rows": rows, "q": query})
    return request_json(url)


def search_arcgis(query: str, rows: int = 12) -> dict[str, Any]:
    url = ARCGIS_SEARCH + "?" + urllib.parse.urlencode({"f": "json", "num": rows, "sortField": "modified", "sortOrder": "desc", "q": query})
    return request_json(url)


class Handler(BaseHTTPRequestHandler):
    server_version = "NeighborhoodLedger/12.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 502) -> None:
        self.send_json({"ok": False, "error": message}, status)

    def serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        try:
            if path in {"/", "/index.html", "/neighborops.html"}:
                return self.serve_file(INDEX)
            if path == "/api/health":
                return self.send_json({"ok": True, "service": "Neighborhood Ledger local companion", "version": 12, "time": dt.datetime.now().isoformat(timespec="seconds")})
            if path == "/api/boundary":
                return self.send_json({"ok": True, "feature": get_boundary(force=params.get("force", [""])[0] == "1")})
            if path == "/api/plats":
                return self.send_json({"ok": True, **scan_plats()})
            if path == "/api/permits":
                return self.send_json({"ok": True, **scan_permits()})
            if path == "/api/project-updates":
                result = {"ok": True, "checkedAt": dt.datetime.now().isoformat(timespec="seconds")}
                try:
                    result["plats"] = {"ok": True, **scan_plats()}
                except Exception as exc:
                    result["plats"] = {"ok": False, "error": str(exc), "results": []}
                try:
                    result["permits"] = {"ok": True, **scan_permits()}
                except Exception as exc:
                    result["permits"] = {"ok": False, "error": str(exc), "results": []}
                return self.send_json(result)
            if path == "/api/grants":
                query = params.get("query", ["community development"])[0].strip() or "community development"
                category = params.get("category", [""])[0]
                rows = max(1, min(20, int(params.get("rows", ["10"])[0])))
                direct = params.get("direct", ["0"])[0] == "1"
                return self.send_json({"ok": True, **scan_grants(query, category, rows, direct)})
            if path == "/api/geocode":
                address = params.get("address", [""])[0].strip()
                if not address:
                    return self.send_error_json("Address is required", 400)
                feature = get_boundary()
                result = dict(geocode(address))
                result["insideCommunity"] = point_in_feature(float(result["lng"]), float(result["lat"]), feature)
                result["communityId"] = profile()["id"]
                return self.send_json({"ok": True, "result": result})
            if path == "/api/ckan":
                query = params.get("q", ["311"])[0]
                return self.send_json({"ok": True, "data": search_ckan(query)})
            if path == "/api/arcgis-search":
                query = params.get("q", [profile()["name"]+" Houston"])[0]
                return self.send_json({"ok": True, "data": search_arcgis(query)})
            safe = (ROOT / path.lstrip("/")).resolve()
            if ROOT in safe.parents:
                return self.serve_file(safe)
            self.send_error(404)
        except Exception as exc:
            self.send_error_json(str(exc))


def main() -> None:
    if not INDEX.exists():
        print(f"Missing {INDEX.name}")
        raise SystemExit(1)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print("\nNeighborhood Ledger — Plat & Permit Activity Build 12")
    print(f"Open: {url}")
    print("Keep this window open while using live scans. Press Ctrl+C to stop.\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Neighborhood Ledger.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
