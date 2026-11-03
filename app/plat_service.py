"""Transport and durable evidence for the Build 12 plat endpoint."""
import datetime as dt
import hashlib
import json
import threading
import urllib.request
import uuid
from pathlib import Path

from plat_ingestion import MAX_BYTES, IngestionError, Snapshot, official_url, scan

ROOT=Path(__file__).resolve().parent
PACKAGED_URL='https://www.houstontx.gov/planning/DevelopRegs/docs_pdfs/Plat_report/2026/Plat-Current-Agenda-Spreadsheet-07-09-2026.xlsx'
PACKAGED_HASH='efa14af1b38f05120725b929bd3b18a6a4dd635d5503992ff985bee51775a768'  # Set from the untouched package below; never recompute trust on reads.
LOCK=threading.Lock()


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_url(newurl):
            raise IngestionError('Redirect outside approved City hosts')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_official(url):
    if not official_url(url): raise IngestionError('Unapproved City URL')
    req=urllib.request.Request(url,headers={'User-Agent':'Neighborhood-Ledger-Reliability/12.1'})
    with urllib.request.build_opener(OfficialRedirects()).open(req,timeout=20) as response:
        if response.url != url:
            raise IngestionError('Source redirected; review canonical URL before ingestion')
        content=response.read(MAX_BYTES+1)
        if len(content)>MAX_BYTES: raise IngestionError('Source exceeds download size limit')
        return content


def cached_snapshot(root):
    pointer=root/'plat_evidence'/'latest.json'
    if pointer.exists():
        meta=json.loads(pointer.read_text(encoding='utf-8'))
        digest=meta['sha256']
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise IngestionError('Invalid cache digest')
        snapshot=Snapshot((pointer.parent/(digest+'.xlsx')).read_bytes(),meta['sourceUrl'],meta['retrievedAt'],digest)
    else:
        snapshot=Snapshot(((root/'plat_cache_2026-07-09.xlsx') if (root/'plat_cache_2026-07-09.xlsx').exists() else ROOT/'plat_cache_2026-07-09.xlsx').read_bytes(),PACKAGED_URL,None,PACKAGED_HASH)
    snapshot.validate()
    return snapshot


def scan_archive(*, root=ROOT, fetch=fetch_official):
    # One complete scan/commit at a time, avoiding half-written cache pointers.
    with LOCK:
        warnings=[]
        try:
            cache=cached_snapshot(root)
        except (OSError,ValueError,KeyError) as exc:
            cache=None
            warnings.append('Prior cache unavailable: '+str(exc))
        downloads={}
        def capture(url):
            downloads[url]=fetch(url)
            return downloads[url]
        result=scan(capture,cache=cache)
        result['warnings'].extend(warnings)
        result['currentAgendaStatus']='unverified'
        result['currentSourceUrl']='https://plattracker.powerappsportals.us/CurrentAgendaSpreadsheet/'
        result['warnings'].append('These are archive records, not a verified current agenda.')
        folder=root/'plat_evidence'
        folder.mkdir(exist_ok=True)
        content=cache.content if result['status']=='cached' else downloads[result['sourceUrl']]
        digest=result['sha256']
        snapshot_file=folder/(digest+'.xlsx')
        if not snapshot_file.exists(): snapshot_file.write_bytes(content)
        run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        result['runId']=run_id
        result['checkedAt']=dt.datetime.now(dt.timezone.utc).isoformat()
        (folder/(run_id+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        if result['status']=='success':
            manifest={k:result[k] for k in ('sourceUrl','retrievedAt','sha256')}
            temporary=folder/(run_id+'.tmp')
            temporary.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            temporary.replace(folder/'latest.json')
        return result

def scan_plats(*,root=ROOT,fetch=fetch_official):
    from public_plats import scan_public
    try: result=scan_public(root)
    except Exception as exc:
        # A fresh scan never reads the packaged workbook or a prior download.
        from plat_ingestion import REPORT_PAGE, discover, ingest, date_iso, workbook_rows
        from urllib.parse import urlsplit
        import re
        try:
            url=discover(fetch(REPORT_PAGE).decode('utf-8-sig'))
            match=re.search(r'(\d{2})-(\d{2})-(\d{4})\.xlsx$',urlsplit(url).path)
            date=dt.date(int(match[3]),int(match[1]),int(match[2]))
            today=dt.datetime.now(dt.timezone.utc).date()
            if not today-dt.timedelta(days=14)<=date<=today+dt.timedelta(days=45):
                raise IngestionError('Newest public workbook is outside the current reporting window: '+date.isoformat())
            content=fetch(url);stamp=dt.datetime.now(dt.timezone.utc).isoformat()
            rows=workbook_rows(content)
            if not rows or any(date_iso(r['values']['date'],r['epoch1904'])!=date.isoformat() for r in rows):
                raise IngestionError('Workbook row dates do not match its advertised report date')
            result=ingest(Snapshot(content,url,stamp,hashlib.sha256(content).hexdigest()))
            result.update(sourceMode='live_dated_report',currentAgendaStatus='dated_report',reportDate=date.isoformat(),checkedAt=stamp,
                freshness='downloaded_now_date_validated',coverage='Latest dated City workbook, downloaded during this check. Not confirmation of the current live agenda or a decision.',
                warnings=['Live agenda unavailable: '+str(exc)+'; using the dated City report shown.'])
            folder=Path(root)/'plat_evidence';folder.mkdir(parents=True,exist_ok=True)
            (folder/(result['sha256']+'.xlsx')).write_bytes(content)
            for row in result['results']:row.update(sourceMode='live_dated_report',retrievedAt=stamp,currentAgendaStatus='dated_report',reportDate=date.isoformat())
        except Exception as fallback:
            return {'status':'failed','results':[],'sourceUrl':REPORT_PAGE,'error':'Live agenda: '+str(exc)+'; dated report: '+str(fallback),
                'warnings':['No verified fresh results. Previously saved records are available in History; no cache was substituted.']}
    from plat_locations import enrich
    return enrich(result,root)
