"""Plat parsing and validation for the Build 12 reliability working copy.

No geocoding: exact workbook membership never implies verified map coordinates.
Only verified official-download snapshots may use the ingestion entry point.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import posixpath
import re
from communities import profile, label, matches_name
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

REPORT_PAGE = 'https://www.houstontx.gov/planning/DevelopRegs/dev_reports.html'
POLICY = 'exact-super-neighborhood-v1'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
MAX_BYTES = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
ALIASES = {
    'neighborhood': ('Super Neighborhood',),
    'case': ('App No.', 'Application No', 'Application Number'),
    'title': ('Subdivision Name',),
    'date': ('PC Date (Cycle) (Review Cycle)', 'PC Date (Cycle)', 'PC Date', 'Review Cycle'),
    'status': ('Application Status', 'Status'),
    'activity': ('Application Type',),
    'activityCode': ('App Type',),
    'special': ('Special Request',),
    'url': ('Download Subdivision Plat PDF File', 'Download Plat', 'Plat PDF'),
    'majorThoroughfare': ('Major Throughfare', 'Major Thoroughfare'),
    'zip': ('Zipcode', 'ZIP Code'),
    'acreage': ('Total Acreage',),
    'lots': ('Number of Lots Created',),
    'developer': ('Developer Company Name',),
    'applicant': ('Applicant Name',),
    'organization': ('Organization',),
    'landUse': ('Land Use',),
    'appraisalId': ('Appraisal District No (County Tax ID)',),
}
REQUIRED = {'neighborhood', 'case', 'title', 'date'}


class IngestionError(ValueError):
    pass


def text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def key(value):
    return re.sub(r'[^a-z0-9]', '', text(value).lower())


def official_url(url):
    u = urlsplit(url)
    return (u.scheme == 'https' and u.hostname in {'houstontx.gov', 'www.houstontx.gov', 'plattracker.powerappsportals.us'}
            and not u.username and not u.password and u.port in {None, 443})


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            self.links.extend(v for k, v in attrs if k.lower() == 'href' and v)


def discover(page, page_url=REPORT_PAGE):
    """Latest dated archive linked by City; never claim this is current agenda."""
    if not official_url(page_url):
        raise IngestionError('Unapproved report host')
    parser = Links()
    parser.feed(page)
    candidates = []
    for href in parser.links:
        url = urljoin(page_url, href)
        if not official_url(url):
            continue
        match = re.search(r'Plat-Current-Agenda-Spreadsheet-(\d{2})-(\d{2})-(\d{4})\.xlsx$', urlsplit(url).path, re.I)
        if not match:
            continue
        month, day, year = map(int, match.groups())
        try:
            date = dt.date(year, month, day)
        except ValueError:
            continue
        candidates.append((date, url))
    if not candidates:
        raise IngestionError('No supported dated City workbook links; source review required')
    return max(candidates)[1]


@dataclass(frozen=True)
class Snapshot:
    content: bytes
    source_url: str
    retrieved_at: str | None
    sha256: str

    def validate(self):
        if not official_url(self.source_url):
            raise IngestionError('Snapshot must identify its actual official download URL')
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise IngestionError('Snapshot hash mismatch')
        if self.retrieved_at is None:
            return  # Packaged artifact has unknown original retrieval time; never invent it.
        try:
            stamp = dt.datetime.fromisoformat(self.retrieved_at.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError()
        except ValueError as exc:
            raise IngestionError('Snapshot retrieval time must include timezone') from exc


def _column(ref):
    match = re.fullmatch(r'([A-Z]+)[1-9]\d*', ref)
    if not match:
        raise IngestionError('Invalid cell reference')
    n = 0
    for char in match[1]:
        n = n * 26 + ord(char) - 64
    return n - 1


def workbook_rows(content):
    """Read all worksheets with exact, unambiguous aliases and physical row numbers."""
    if len(content) > MAX_BYTES:
        raise IngestionError('Workbook exceeds size limit')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_EXPANDED:
                raise IngestionError('Workbook exceeds expanded size limit')
            book = ET.fromstring(z.read('xl/workbook.xml'))
            props = book.find('m:workbookPr', NS)
            epoch1904 = props is not None and props.get('date1904', '').lower() in {'1', 'true'}
            rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            targets = {r.get('Id'):r.get('Target') for r in rels if r.get('TargetMode') != 'External'}
            shared = []
            if 'xl/sharedStrings.xml' in z.namelist():
                shared = [''.join(t.text or '' for t in si.findall('.//m:t', NS)) for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
            records, found_schema = [], False
            for sheet in book.findall('m:sheets/m:sheet', NS):
                target = targets.get(sheet.get('{'+NS['r']+'}id'))
                if not target:
                    raise IngestionError('Missing worksheet relationship')
                path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl',target))
                if not path.startswith('xl/'):
                    raise IngestionError('Invalid worksheet path')
                root = ET.fromstring(z.read(path))
                header = None
                for row in root.findall('m:sheetData/m:row', NS):
                    values = {}
                    for cell in row.findall('m:c', NS):
                        value = cell.findtext('m:v', '', NS)
                        if cell.get('t') == 'inlineStr':
                            value = ''.join(t.text or '' for t in cell.findall('.//m:t', NS))
                        elif cell.get('t') == 's':
                            value = shared[int(value)]
                        elif cell.get('t') == 'e':
                            raise IngestionError('Workbook contains an Excel cell error')
                        if cell.find('m:f', NS) is not None and value == '':
                            raise IngestionError('Formula has no cached value')
                        values[_column(cell.get('r',''))] = text(value)
                    if not any(values.values()):
                        continue
                    mapping = {}
                    for name, aliases in ALIASES.items():
                        positions = [i for i,v in values.items() if key(v) in {key(a) for a in aliases}]
                        if len(positions) > 1:
                            raise IngestionError('Ambiguous columns for '+name)
                        if positions:
                            mapping[name] = positions[0]
                    if REQUIRED <= mapping.keys():
                        header = mapping
                        found_schema = True
                        continue
                    if header is None:
                        continue
                    records.append({'sheet':sheet.get('name'), 'row':int(row.get('r','0')),
                                    'values':{name:values.get(i,'') for name,i in header.items()},
                                    'rawCells':values, 'epoch1904':epoch1904})
            if not found_schema:
                raise IngestionError('Required plat schema not found; not an empty successful scan')
            return records
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, ValueError) as exc:
        if isinstance(exc, IngestionError):
            raise
        raise IngestionError('Invalid or unsupported workbook: '+str(exc)) from exc


def date_iso(value, epoch1904=False):
    for fmt in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y','%Y/%m/%d'):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        serial = float(value)
        if 30000 < serial < 70000:
            epoch = dt.datetime(1904,1,1) if epoch1904 else dt.datetime(1899,12,30)
            return (epoch+dt.timedelta(days=serial)).date().isoformat()
    except ValueError:
        pass
    raise IngestionError('Missing or invalid Planning Commission date')


def ingest(snapshot, *, mode='live_archive', attempted_url=None, warnings=None):
    snapshot.validate()
    if mode not in {'live_archive','cache','officer_import'}:
        raise IngestionError('Unknown source mode')
    if mode == 'live_archive' and snapshot.retrieved_at is None:
        raise IngestionError('Live retrieval requires a timestamp')
    rows = workbook_rows(snapshot.content)
    accepted, rejected, by_identity = [], [], {}
    for row in rows:
        v = row['values']
        reason = None
        if not matches_name(v['neighborhood']):
            reason = 'not_exact_selected_neighborhood'
        elif not v['case'] or not v['title']:
            reason = 'missing_identity'
        else:
            try:
                date = date_iso(v['date'],row['epoch1904'])
            except IngestionError:
                reason = 'invalid_pc_date'
        if reason:
            rejected.append({'sheet':row['sheet'],'row':row['row'],'reason':reason,'rawCells':row['rawCells']})
            continue
        identity = 'plat:'+v['case']+':'+date
        provenance = {'sourceUrl':snapshot.source_url,'retrievedAt':snapshot.retrieved_at,
                      'sha256':snapshot.sha256,'sheet':row['sheet'],'row':row['row'],
                      'rawCells':row['rawCells'],'geographyPolicy':POLICY,'sourceMode':mode}
        if identity in by_identity:
            prior = by_identity[identity]
            if prior['sourceValues'] != v:
                raise IngestionError('Conflicting rows for '+identity+'; refusing arbitrary overwrite')
            prior['provenance'].append(provenance)
            continue
        link = v.get('url','')
        if urlsplit(link).scheme not in {'http','https'} or not urlsplit(link).hostname:
            link = snapshot.source_url
        record = {'kind':'Plat','externalKey':identity,'caseNo':v['case'],'title':v['title'],
                  'date':date,'status':v.get('status') or 'Not provided','activity':v.get('activity') or v.get('activityCode',''),
                  'special':v.get('special',''),'sourceUrl':snapshot.source_url,'url':link,
                  'source':'Houston Planning Plat Activity Report',
                  'location':label(),
                  'summary':f"{v['title']}. Planning Commission date: {date}. The workbook identifies the case as {profile()['officialName']}.",
                  'matchMethod':'Exact City Super Neighborhood field match',
                  'mapStatus':'Needs a verified address or parcel location',
                  'sourceValues':v,'provenance':[provenance]}
        for name in ('majorThoroughfare','acreage','lots','developer','applicant','organization','landUse','appraisalId'):
            record[name]=v.get(name,'')
        by_identity[identity]=record
        accepted.append(record)
    return {'status':'cached' if mode=='cache' else 'success', 'sourceMode':mode,
            'freshness':'cached_snapshot' if mode=='cache' else 'latest_discovered_archive_not_current_agenda',
            'sourceUrl':snapshot.source_url,'attemptedUrl':attempted_url,
            'retrievedAt':snapshot.retrieved_at,'sha256':snapshot.sha256,
            'totalRows':len(rows),'results':accepted,'rejected':rejected,
            'warnings':list(warnings or []) + (['Original snapshot retrieval time is unknown'] if snapshot.retrieved_at is None else []),
            'strictFilter':'Super Neighborhood = '+profile()['officialName']}


def scan(fetch, *, cache=None, now=None):
    """Injected transport must enforce official URLs/redirects, timeout and size limits.

    Cache is explicit: actual URL, original retrieval time, bytes and hash travel together.
    No guessed fixed-date fallback or implicit cache replacement.
    """
    attempted = None
    try:
        page = fetch(REPORT_PAGE).decode('utf-8-sig')
        attempted = discover(page)
        content = fetch(attempted)
        stamp = now or dt.datetime.now(dt.timezone.utc).isoformat()
        snapshot = Snapshot(content,attempted,stamp,hashlib.sha256(content).hexdigest())
        return ingest(snapshot,attempted_url=attempted)
    except (OSError, IngestionError, UnicodeError) as exc:
        if cache is None:
            raise IngestionError('Plat scan failed: '+str(exc)) from exc
        return ingest(cache,mode='cache',attempted_url=attempted,warnings=[str(exc)])
