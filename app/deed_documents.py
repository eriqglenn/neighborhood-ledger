"""User-operated County browser, persistent sign-in, and local recorded-PDF library."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
import uuid

from deed_search import CLERK, checked_url, parse_records, clean

MAX_BYTES = 100 * 1024 * 1024
CLERK_HOSTS = {'www.cclerk.hctx.net','cclerk.hctx.net'}

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def pdf_pages(content):
    import pymupdf
    if len(content)>MAX_BYTES or not content.lstrip().startswith(b'%PDF-'):
        raise ValueError('The download is not a PDF under 100 MB. Download the complete PDF from the County viewer.')
    try:
        with pymupdf.open(stream=content,filetype='pdf') as doc:
            if doc.needs_pass or not doc.is_pdf or not 0<len(doc)<=3000:
                raise ValueError('The recording is empty, protected, or too large to preview.')
            return len(doc)
    except Exception as e:
        raise ValueError('The download could not be read as a complete PDF recording.') from e

class DocumentLibrary:
    def __init__(self, root):
        self.root=Path(root)/'deed_documents'
    def _id(self, doc_id):
        if not isinstance(doc_id,str) or not re.fullmatch(r'[a-f0-9]{32}',doc_id):
            raise ValueError('Invalid saved document.')
        return doc_id
    def metadata(self, doc_id):
        path=self.root/(self._id(doc_id)+'.json')
        if not path.is_file(): raise ValueError('Saved recording not found.')
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('id')!=doc_id: raise ValueError('Saved recording metadata does not match.')
        return data
    def content(self, doc_id):
        meta=self.metadata(doc_id)
        content=(self.root/(doc_id+'.pdf')).read_bytes()
        if hashlib.sha256(content).hexdigest()!=meta['sha256']:
            raise ValueError('The saved PDF has changed. Download a fresh copy from the County.')
        return content
    def list(self, account):
        if not re.fullmatch(r'\d{13}',account or ''):raise ValueError('Select a valid HCAD property.')
        results=[]
        if self.root.exists():
            for file in self.root.glob('*.json'):
                try:
                    data=self.metadata(file.stem)
                    if data.get('account')==account and (self.root/(file.stem+'.pdf')).is_file():results.append(data)
                except (ValueError,OSError,KeyError):continue
        return sorted(results,key=lambda x:x['savedAt'],reverse=True)
    def save(self, account, record, content, source_url):
        if not re.fullmatch(r'\d{13}',account or ''):raise ValueError('Invalid HCAD property.')
        source_url=checked_url(source_url,clerk_only=True)
        pages=pdf_pages(content);digest=hashlib.sha256(content).hexdigest()
        for old in self.list(account):
            if old.get('sha256')==digest and old.get('record',{}).get('fileNumber')==record['fileNumber']:
                if self.content(old['id'])==content:return old
        self.root.mkdir(parents=True,exist_ok=True)
        doc_id=uuid.uuid4().hex
        meta={'id':doc_id,'account':account,'record':record,'pages':pages,'sha256':digest,'savedAt':timestamp(),'sourceUrl':source_url,'reviewStatus':'Review the PDF against the selected recording and property before relying on it.'}
        meta['identityStatus']='unconfirmed'
        meta['reviewStatus']='Check that the downloaded PDF is file '+record['fileNumber']+'. This is a downloaded copy awaiting your confirmation, not a verified recording match.'
        if str(record.get('pages','')).isdigit() and int(record['pages'])!=pages:
            meta['reviewStatus']+=' Page count differs: the County index lists '+str(record['pages'])+' pages; this PDF contains '+str(pages)+'. Check for missing pages.'
        pdf=self.root/(doc_id+'.pdf');sidecar=self.root/(doc_id+'.json')
        try:
            with pdf.open('xb') as f:f.write(content)
            with sidecar.open('x',encoding='utf-8') as f:json.dump(meta,f,indent=2)
        except Exception:
            pdf.unlink(missing_ok=True);sidecar.unlink(missing_ok=True);raise
        return meta
    def confirm(self, doc_id):
        meta=self.metadata(doc_id);self.content(doc_id)
        meta.update(identityStatus='user-confirmed',confirmedAt=timestamp(),reviewStatus='You confirmed the downloaded PDF matches file '+meta['record']['fileNumber']+'. Review its legal description and related documents to determine applicability.')
        path=self.root/(doc_id+'.json');temp=self.root/(doc_id+'.json.tmp')
        temp.write_text(json.dumps(meta,indent=2),encoding='utf-8');temp.replace(path)
        return meta
    def discard(self, doc_id):
        meta=self.metadata(doc_id)
        if meta.get('identityStatus')=='user-confirmed':raise ValueError('This copy is confirmed; only unconfirmed downloads can be discarded here.')
        (self.root/(self._id(doc_id)+'.pdf')).unlink(missing_ok=True)
        (self.root/(doc_id+'.json')).unlink(missing_ok=True)
    def page(self, doc_id, number):
        import pymupdf
        with pymupdf.open(stream=self.content(doc_id),filetype='pdf') as doc:
            if not 1<=number<=len(doc):raise ValueError('Page number is outside this recording.')
            page=doc[number-1]
            scale=min(2,1600/max(page.rect.width,1),2200/max(page.rect.height,1))
            return page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png')

def choose_record(records, selected):
    candidates=[r for r in records if r['fileNumber']==selected['fileNumber']]
    if selected.get('filmCode'):
        candidates=[r for r in candidates if r.get('filmCode')==selected['filmCode']]
    if len(candidates)!=1:raise ValueError('The County did not return one exact match for this recording. Search again before opening it.')
    record=candidates[0]
    if not record.get('viewerUrl'):raise ValueError('The County supplies no online image for this recording. Use its file number to request a copy.')
    checked_url(record['viewerUrl'],clerk_only=True)
    return record

class CountyBrowser:
    def __init__(self, root):
        self.root=Path(root);self.library=DocumentLibrary(root)
        self.profile=self.root/'CountyClerkBrowser'
        self.lock=threading.Lock();self.cancel=threading.Event();self.thread=None
        self.state={'status':'idle','message':'Select a recording to view or download.'}
    def status(self):
        with self.lock:return dict(self.state)
    def update(self, **values):
        with self.lock:self.state.update(values)
    def start(self, account, record, *, headless=False, timeout=1200):
        if not re.fullmatch(r'\d{13}',account or ''):raise ValueError('Select a valid property.')
        if not re.fullmatch(r'[A-Za-z0-9-]{1,40}',record.get('fileNumber','')):raise ValueError('Select a valid recording.')
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Finish or cancel the current County browser first.')
            self.cancel=threading.Event()
            self.state={'status':'opening','account':account,'fileNumber':record['fileNumber'],'message':'Opening the County browser and refreshing this recording’s link.'}
            self.thread=threading.Thread(target=self._run,args=(account,dict(record),headless,timeout),daemon=True)
            self.thread.start()
        return self.status()
    def close(self):self.cancel.set()
    def _launch_browser(self, playwright, headless):
        errors=[]
        for channel in ('msedge','chrome'):
            try:
                return playwright.chromium.launch_persistent_context(str(self.profile),channel=channel,headless=headless,accept_downloads=True,viewport={'width':1280,'height':900})
            except Exception as e:errors.append(str(e).splitlines()[0])
        raise ValueError('Could not open Edge or Chrome. Close another Ledger County browser and retry. '+'; '.join(errors))
    def _resolve(self, page, selected):
        self.update(status='opening',message='Finding the selected file number in the County’s current index…')
        page.goto(CLERK,wait_until='domcontentloaded',timeout=45000)
        field=page.locator('input[aria-label="File Number"]')
        field.wait_for(timeout=30000);field.fill(selected['fileNumber'])
        with page.expect_navigation(wait_until='domcontentloaded',timeout=45000):
            page.locator('input[type="submit"][value="Search"]').click()
        rows,_=parse_records(page.content())
        return choose_record(rows,selected)
    def _run(self, account, selected, headless, timeout):
        context=None;captured=[];last_error=[]
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                context=self._launch_browser(p,headless)
                import county_session
                county_session.restore(context,self.root)
                page=context.pages[0] if context.pages else context.new_page()
                for tab in list(context.pages):
                    if tab!=page:tab.close()
                current=self._resolve(page,selected)
                viewer=[current['viewerUrl']]
                pending_pdfs=[];pending_downloads=[]
                def accept(content, source, tab):
                    if captured or self.cancel.is_set():return
                    meta=self.library.save(account,current,content,source)
                    captured.append(meta)
                    self.update(status='capturing',message='PDF captured. Finishing the saved copy and County session…')
                def document_route(route):
                    # Capture the original authenticated response before Edge's PDF extension
                    # takes ownership. Re-requesting a one-use viewer URL can return HTML.
                    response=route.fetch(timeout=45000,max_redirects=5)
                    checked_url(response.url,clerk_only=True)
                    if response.status==200 and 'application/pdf' in response.headers.get('content-type','').lower():
                        if int(response.headers.get('content-length','0'))>MAX_BYTES:
                            return route.fulfill(response=response)
                        content=response.body()
                        if content.lstrip().startswith(b'%PDF-') and len(content)<=MAX_BYTES:
                            accept(content,response.url,page)
                            return route.fulfill(status=200,content_type='text/html',body='<p>The recording was saved. Return to Neighborhood Ledger to preview it.</p>')
                    route.fulfill(response=response)
                context.route(re.compile(r'https://(?:www\.)?cclerk\.hctx\.net/Applications/WebSearch/EComm/(?:ViewEdocs|PrintDocument)\.aspx(?:\?|$)',re.I),document_route)
                def watch(tab):
                    # Only the selected browser tab and popups it opens can supply a PDF.
                    if tab!=page:
                        opener=tab.opener()
                        while opener and opener!=page:opener=opener.opener()
                        if opener!=page:return
                    def response(r):
                        if captured or self.cancel.is_set():return
                        try:
                            if urlsplit(r.url).hostname not in CLERK_HOSTS or r.status!=200:return
                            if 'application/pdf' not in r.headers.get('content-type','').lower():return
                            if int(r.headers.get('content-length','0'))>MAX_BYTES:return
                            if 'attachment' not in r.headers.get('content-disposition','').lower():pending_pdfs.append((r,tab))
                        except Exception as e:last_error[:]=[str(e)]
                    def download(d):
                        if captured or self.cancel.is_set():return
                        pending_downloads.append((d,tab))
                    tab.on('response',response);tab.on('download',download)
                watch(page);context.on('page',watch)
                page.goto(viewer[0],wait_until='domcontentloaded',timeout=45000)
                if urlsplit(page.url).hostname in CLERK_HOSTS and 'login.aspx' not in page.url.lower():viewer[0]=page.url
                deadline=time.monotonic()+timeout;saw_login=False;resumed=False;last_session_save=0
                while not captured and not self.cancel.is_set() and time.monotonic()<deadline:
                    # Process download bodies outside browser event callbacks to avoid reentrant waits.
                    try:
                        while pending_downloads and not captured:
                            download,tab=pending_downloads.pop(0);source=download.url
                            if source.startswith('blob:'):
                                checked_url(source[5:],clerk_only=True);source=viewer[0]
                            else:checked_url(source,clerk_only=True)
                            path=download.path()
                            if not path or Path(path).stat().st_size>MAX_BYTES:raise ValueError('The download is missing or larger than 100 MB.')
                            accept(Path(path).read_bytes(),source,tab)
                        while pending_pdfs and not captured:
                            response,tab=pending_pdfs.pop(0);content=b''
                            try:content=response.body()
                            except Exception:pass
                            if not content.lstrip().startswith(b'%PDF-') and response.request.method=='GET':
                                fetched=context.request.get(response.url,timeout=30000)
                                if fetched.status==200:content=fetched.body()
                            if content:accept(content,response.url,tab)
                    except Exception as e:
                        last_error[:]=[str(e)];self.update(status='waiting',message=str(e)+' Use the County’s complete PDF download.')
                    if captured:break
                    if page.is_closed():break
                    logged_out='login.aspx' in page.url.lower() or page.locator('input[type="password"]').count()>0
                    if not logged_out and time.monotonic()-last_session_save>5:
                        try:county_session.save(context,self.root)
                        except OSError:pass
                        last_session_save=time.monotonic()
                    if logged_out:
                        saw_login=True
                        self.update(status='login',message='Sign in to your free County Clerk account in the browser window. Ledger will return to file '+selected['fileNumber']+' after sign-in.')
                    elif saw_login and not resumed:
                        # Re-query in the authenticated browser instead of reusing a pre-login token.
                        current=self._resolve(page,selected);viewer[0]=current['viewerUrl'];resumed=True
                        page.goto(viewer[0],wait_until='domcontentloaded',timeout=45000)
                        if urlsplit(page.url).hostname in CLERK_HOSTS and 'login.aspx' not in page.url.lower():viewer[0]=page.url
                    elif not last_error:
                        self.update(status='waiting',message='In the County viewer, open or download the complete PDF for file '+selected['fileNumber']+'. Ledger will save it for preview.')
                    page.wait_for_timeout(300)
                if captured:
                    self.update(status='capturing',message='Finishing the saved copy and County session…')
                else:
                    self.update(status='cancelled' if self.cancel.is_set() else 'closed',message='No PDF was saved. You can reopen the selected recording and try again.'+((' '+last_error[0]) if last_error else ''))
                county_session.save(context,self.root)
                context.close();context=None
        except Exception as e:
            self.update(status='error',message='Could not finish opening this recording: '+str(e))
        finally:
            if context:
                try:
                    import county_session
                    county_session.save(context,self.root)
                except Exception:pass
                try:context.close()
                except Exception:pass
            if captured:self.update(status='saved',document=captured[0],message='PDF captured for review. Open its preview and confirm the printed recording number before using it.')
