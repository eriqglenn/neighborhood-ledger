import base64
import datetime as dt
import hashlib
import json
import logging
import re
import secrets
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

import neighborops_server as legacy
from paths import APP_DIR, VERSION
from storage import Store,Conflict,utcnow
from monitor import Monitor
from news_policy import POLICY
from plat_ingestion import Snapshot,ingest
import communities

class CommunityServer(ThreadingHTTPServer):
    def community_services(self):
        ident=communities.profile()['id']
        with self.community_lock:
            if ident not in self.services:
                import plat_service
                store=Store(communities.data_root(self.data_root,ident))
                monitor=Monitor(store,lambda:plat_service.scan_plats(root=store.root),legacy.scan_permits)
                self.services[ident]=(store,monitor)
                monitor.start()
            return self.services[ident]
    @property
    def store(self): return self.community_services()[0]
    @property
    def monitor(self): return self.community_services()[1]
    def settings(self):
        value=self.store.settings()
        with communities.selected('55'):value['autoStart']=self.store.settings().get('autoStart',False)
        return value
    def shutdown(self):
        with self.community_lock:
            for store,monitor in self.services.values():monitor.stop.set()
        return super().shutdown()

def community_html(html):
    p=communities.profile()
    # Only application templates are personalized; saved user text is never rewritten.
    if p['id']!='55':
        for old,new in [('GREATER FIFTH WARD',p['officialName']),('Greater Fifth Ward',p['name']),('Fifth Ward',p['name']),('Super Neighborhood 55','Super Neighborhood '+p['id']),('SN 55','SN '+p['id']),('SN55','SN'+p['id']),('/superneighborhoods/55.html','/superneighborhoods/'+p['id']+'.html'),('The Nickel Community Brief',p['name']+' Community Brief')]:
            html=html.replace(old,new)
    return html

class Handler(legacy.Handler):
    def log_message(self,fmt,*args): logging.info(fmt,*args)
    def host_ok(self): return self.headers.get('Host') in {'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
    def in_community(self,method):
        query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        page=urllib.parse.urlsplit(self.path).path in {'/','/index.html','/neighborops.html'}
        ident=self.headers.get('X-Ledger-Community') or query.get('community',[communities.remembered(self.server.data_root) if page else '55'])[0]
        try:
            with communities.selected(ident):return method()
        except ValueError as error:return self.send_error_json(str(error),400)
    def do_GET(self):return self.in_community(self.get_community)
    def do_POST(self):return self.in_community(self.post_community)
    def get_community(self):
        if not self.host_ok(): return self.send_error_json('Local access only',403)
        path=urllib.parse.urlsplit(self.path).path
        try:
            if path in {'/','/neighborops.html','/index.html'}:
                html=(APP_DIR/'neighborops.html').read_text(encoding='utf-8')
                html=html.replace('/*OFFICE_TOKEN*/',json.dumps(self.server.token)).replace('/*OFFICE_EXTENSION*/',(APP_DIR/'news-dedup.js').read_text(encoding='utf-8')+'\n'+(APP_DIR/'office.js').read_text(encoding='utf-8'))
                html=html.replace('/*DESIGN_EXTENSION*/',(APP_DIR/'design.js').read_text(encoding='utf-8'))
                html=html.replace('/*DEED_EXTENSION*/',(APP_DIR/'deeds.js').read_text(encoding='utf-8'))
                html=html.replace('/*COMMUNITY_EXTENSION*/',(APP_DIR/'community.js').read_text(encoding='utf-8'))
                html=html.replace('/*CASE_EXTENSION*/',(APP_DIR/'cases.js').read_text(encoding='utf-8'))
                html=html.replace('/*DOCUMENT_COLORS_EXTENSION*/',(APP_DIR/'document-colors.js').read_text(encoding='utf-8'))
                html=html.replace('/*DOCUMENT_COLORS_STYLE*/',(APP_DIR/'document-colors.css').read_text(encoding='utf-8'))
                html=html.replace('/*MLS_EXTENSION*/',(APP_DIR/'mls.js').read_text(encoding='utf-8')).replace('/*MLS_STYLE*/',(APP_DIR/'mls.css').read_text(encoding='utf-8'))
                html=html.replace('/*REQUESTS_EXTENSION*/',(APP_DIR/'requests.js').read_text(encoding='utf-8')).replace('/*REQUESTS_STYLE*/',(APP_DIR/'requests.css').read_text(encoding='utf-8'))
                html=html.replace('/*ASSISTANT_EXTENSION*/','').replace('/*ASSISTANT_STYLE*/','')
                html=community_html(html)
                boot={'selected':communities.profile(),'communities':communities.CATALOG['communities']}
                html=html.replace('/*COMMUNITY_BOOT*/',json.dumps(boot).replace('</','<\\/'))
                raw=html.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw);return
            if path.startswith('/api/mls/'):
                import mls_service
                return mls_service.handle_get(self,path,urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
            if path.startswith('/api/ai/'):return self.send_error_json('AI is not included in this edition.',404)
            if path=='/api/health': return self.send_json({'ok':True,'product':'NeighborhoodLedgerMLSNoAIOffice','version':VERSION,'dataPath':str(self.server.store.root),'ai':False})
            if path=='/api/workspace': return self.send_json(self.server.store.workspace())
            if path=='/api/settings': return self.send_json(self.server.settings())
            if path=='/api/communities':return self.send_json({'selected':communities.profile(),**communities.CATALOG})
            if path=='/api/bylaws':
                import bylaws
                return self.send_json(bylaws.lookup())
            if path=='/api/news-policy': return self.send_json(POLICY)
            if path=='/api/deeds/browser': return self.send_json(self.server.deed_browser.status())
            if path=='/api/deeds/documents':
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                return self.send_json({'documents':self.server.deed_browser.library.list(query.get('account',[''])[0])})
            document=re.fullmatch(r'/api/deeds/documents/([a-f0-9]{32})/(download|page/(\d+))',path)
            if document:
                library=self.server.deed_browser.library;doc_id=document[1]
                if document[2]=='download':
                    content=library.content(doc_id);mime='application/pdf'
                else:
                    content=library.page(doc_id,int(document[3]));mime='image/png'
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                if document[2]=='download':self.send_header('Content-Disposition','attachment; filename="Deed-recording-'+doc_id+'.pdf"')
                self.end_headers();self.wfile.write(content);return
            if path in {'/api/deeds/property','/api/deeds/records','/api/deeds/subdivision'}:
                import deed_search
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    if path.endswith('/property'):
                        if any(key in query for key in ('number','street','zip')):
                            result=deed_search.find_properties_fields(query.get('number',[''])[0],query.get('street',[''])[0],query.get('zip',[''])[0])
                        else:
                            result=deed_search.find_properties(query.get('address',[''])[0])
                    elif path.endswith('/subdivision'):
                        result=deed_search.search_subdivision(query.get('name',[''])[0],query.get('section',[''])[0])
                    else:
                        result=deed_search.search_restrictions(query.get('account',[''])[0])
                    if path.endswith('/records'):
                        account=result['property']['account']
                        with self.server.deed_record_lock:
                            for record in result['records']:
                                self.server.deed_records[(account,record['fileNumber'],record.get('filmCode',''))]=record
                    return self.send_json({'ok':True,**result})
                except ValueError as error:
                    return self.send_error_json(str(error),400)
            if path=='/design.css': return self.serve_file(APP_DIR/'design.css')
            if path=='/api/monitor': return self.send_json(self.server.monitor.status())
            if path=='/api/findings': return self.send_json({'results':self.server.store.findings()})
            if path=='/api/source-report':
                source=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('source',[''])[0]
                with self.server.store.connect() as c:
                    row=c.execute('SELECT body FROM scans WHERE source=? ORDER BY started DESC LIMIT 1',(source,)).fetchone()
                return self.send_json(json.loads(row[0]) if row else {'error':'No scan yet'})
            if path=='/api/backups': return self.send_json({'results':self.server.store.backups()})
            if path=='/api/changes':
                with self.server.store.connect() as c: rows=[dict(r) for r in c.execute('SELECT revision,changed,actor FROM history ORDER BY id DESC LIMIT 50')]
                return self.send_json({'results':rows})
            if path.startswith('/vendor/'):
                target=(APP_DIR/path.lstrip('/')).resolve()
                if (APP_DIR/'vendor').resolve() not in target.parents: return self.send_error(404)
                return self.serve_file(target)
            if path in {'/api/plats','/api/permits'}:
                import plat_service
                name=path.rsplit('/',1)[1];data=plat_service.scan_plats(root=self.server.store.root) if name=='plats' else legacy.scan_permits()
                self.server.store.record_scan(name,data);return self.send_json({'ok':True,**data})
            if path in {'/api/boundary','/api/geocode','/api/grants','/api/ckan','/api/arcgis-search'}: return super().do_GET()
            return self.send_error(404)
        except Exception as e:
            logging.exception('GET failed');return self.send_error_json(str(e))
    def post_community(self):
        origin=self.headers.get('Origin')
        allowed={'http://127.0.0.1:'+str(self.server.server_port),'http://localhost:'+str(self.server.server_port)}
        if not self.host_ok() or (origin and origin not in allowed) or self.headers.get('X-Ledger-Token')!=self.server.token: return self.send_error_json('Open the local application to perform this action',403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<16_000_000: return self.send_error_json('Invalid request size',413)
            body=json.loads(self.rfile.read(length));path=urllib.parse.urlsplit(self.path).path;store=self.server.store
            if path.startswith('/api/ai/'):return self.send_error_json('AI is not included in this edition.',404)
            if path.startswith('/api/mls/'):
                import mls_service
                return self.send_json(mls_service.handle_post(self,path,body))
            if path=='/api/311/status':
                import case_status
                return self.send_json(case_status.lookup(body.get('caseNumber')))
            if path=='/api/community-selection':
                ident=communities.profile(body.get('id',''))['id']
                with self.server.community_lock:communities.remember(self.server.data_root,ident)
                return self.send_json({'id':ident,'url':'/?community='+ident+'&refresh=1'})
            if path=='/api/deeds/open':
                key=(body.get('account'),body.get('fileNumber'),body.get('filmCode',''))
                with self.server.deed_record_lock:record=self.server.deed_records.get(key)
                if record is None:raise ValueError('Search this property again before opening the recording.')
                return self.send_json(self.server.deed_browser.start(key[0],record))
            if path=='/api/deeds/cancel':
                self.server.deed_browser.close();return self.send_json({'ok':True})
            if path=='/api/deeds/confirm':
                return self.send_json(self.server.deed_browser.library.confirm(body.get('id')))
            if path=='/api/deeds/discard':
                self.server.deed_browser.library.discard(body.get('id'));return self.send_json({'ok':True})
            if path=='/api/workspace':
                revision=store.save(body['state'],body['revision'],store.settings().get('actor','Local officer'));return self.send_json({'revision':revision})
            if path=='/api/settings':
                old=self.server.settings()
                candidate={**old,**body}
                # Validate settings before changing the Windows startup preference.
                if not 30<=int(candidate['intervalMinutes'])<=1440 or not 1<=int(candidate['days'])<=90: raise ValueError('Invalid monitoring interval or news window')
                if bool(old.get('autoStart'))!=bool(candidate.get('autoStart')):
                    from desktop import configure_autostart
                    configure_autostart(bool(candidate.get('autoStart')))
                    with communities.selected('55'):
                        base=self.server.store; base.settings({**base.settings(),'autoStart':bool(candidate.get('autoStart'))})
                store.settings(candidate)
                return self.send_json(self.server.settings())
            if path=='/api/scan': return self.send_json({'started':self.server.monitor.trigger(body.get('source','all'))})
            if path=='/api/backup': return self.send_json({'name':store.backup()})
            if path=='/api/restore':
                if self.server.monitor.running: raise ValueError('Wait for the current source check to finish before restoring')
                return self.send_json({'safetyBackup':store.restore(body['name'])})
            if path=='/api/import/plats':
                if body.get('confirmedOfficial') is not True or not body.get('officer','').strip(): raise ValueError('Officer source confirmation is required')
                source=body.get('sourceUrl','');host=urllib.parse.urlsplit(source).hostname
                if host not in {'www.houstontx.gov','houstontx.gov','plattracker.powerappsportals.us'} or not source.startswith('https://'): raise ValueError('Record the actual City or PlatTracker download page URL')
                content=base64.b64decode(body['content'],validate=True)
                snap=Snapshot(content,source,utcnow(),hashlib.sha256(content).hexdigest())
                data=ingest(snap,mode='officer_import')
                data.update(status='officer_import',retrievedAt=None,importedAt=utcnow(),freshness='officer_import_not_independently_confirmed',currentAgendaStatus='officer_supplied_not_independently_confirmed',warnings=['Officer-supplied workbook. Current agenda and source were not independently fetched.'])
                for record in data['results']:
                    for p in record['provenance']: p.update(officer=body['officer'],filename=body.get('filename'),sourceMethod='Officer-confirmed City download',retrievedAt=None,importedAt=utcnow())
                folder=store.root/'plat_evidence';folder.mkdir(exist_ok=True);(folder/(snap.sha256+'.xlsx')).write_bytes(content)
                (folder/(snap.sha256+'-import.json')).write_text(json.dumps(data,indent=2),encoding='utf-8')
                store.record_scan('plat-import',data);return self.send_json({'ok':True,**data})
            if path=='/api/import/permits':
                if body.get('confirmedOfficial') is not True: raise ValueError('Confirm the official source of the report')
                data=legacy.scan_permits(body['html'],'Officer-imported Houston E-Report')
                data['warnings'].append('Officer-imported report; official origin not independently downloaded')
                store.record_scan('permit-import',data);return self.send_json({'ok':True,**data})
            if path=='/api/shutdown':
                self.server.deed_browser.close()
                self.send_json({'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            return self.send_error(404)
        except Conflict as e: return self.send_error_json(str(e),409)
        except (ValueError,KeyError,TypeError) as e: return self.send_error_json(str(e),400)
        except Exception as e:
            logging.exception('POST failed');return self.send_error_json(str(e))

def create_server(port,root):
    legacy.CACHE_FILE=Path(root)/'geography-cache.json';legacy.CACHE=legacy.load_cache()
    server=CommunityServer(('127.0.0.1',port),Handler);server.token=secrets.token_urlsafe(32)
    server.data_root=Path(root);server.services={};server.community_lock=threading.RLock()
    from deed_documents import CountyBrowser
    server.deed_browser=CountyBrowser(root);server.deed_records={};server.deed_record_lock=threading.Lock()
    with communities.selected('55'):server.community_services()
    with communities.selected(communities.remembered(root)):server.community_services()
    return server
