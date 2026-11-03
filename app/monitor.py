import datetime as dt
import threading
import time
from pathlib import Path
import hashlib

from council_sources import fetch_district, parse_district
from paths import VERSION
from collectors import SOURCES, sources_for_community, fetch_feed, parse_feed
from communities import profile, selected
from community_sources import parse_calendar, parse_notices, parse_classes

class Monitor:
    def __init__(self,store,plats,permits):
        self.community_id=store.community_id
        with selected(self.community_id):self.sources=sources_for_community()
        self.store=store;self.plats=plats;self.permits=permits
        self.running=False;self.current='';self.last_finished=None;self.lock=threading.Lock();self.stop=threading.Event()
    def start(self):
        threading.Thread(target=self.loop,name='Ledger scheduler',daemon=True).start()
    def trigger(self,source='all'):
        if source not in {'all','news','plats','permits','development'}: raise ValueError('Unknown scan type')
        with self.lock:
            if self.running: return False
            self.running=True
        names=([s['id'] for s in self.sources] if source in {'all','news'} else [])+([n for n in ('plats','permits') if source in {'all','development',n}])
        for name in names:self.store.record_scan(name,{'status':'running','results':[],'warnings':['Fresh check in progress; saved results remain in History.']})
        threading.Thread(target=self.run,args=(source,),name='Ledger source checks',daemon=True).start();return True
    def run(self,selection):
        with selected(self.community_id):
            self._run(selection)
    def _run(self,selected):
        try:
            if selected in {'all','news'}:
                settings=self.store.settings()
                for source in self.sources:
                    self.current=source['name']
                    try:
                        raw=fetch_district(source) if source.get('format')=='council' else fetch_feed(source);digest=hashlib.sha256(raw).hexdigest()
                        folder=self.store.root/'source_evidence';folder.mkdir(exist_ok=True)
                        extension={'council':'.json','ical':'.ics','html':'.html','classes':'.html'}.get(source.get('format'),'.xml')
                        (folder/(digest+extension)).write_bytes(raw)
                        parser={'council':parse_district,'ical':parse_calendar,'html':parse_notices,'classes':parse_classes}.get(source.get('format'),parse_feed)
                        result=parser(raw,source,days=int(settings.get('days',30)),keywords=settings.get('keywords'))
                        result['sha256']=digest
                        for r in result['results']: r['sourceHash']=digest
                    except Exception as e: result={'status':'failed','results':[],'error':str(e),'sourceUrl':source['url']}
                    self.store.record_scan(source['id'],result)
            for name,fn in [('plats',self.plats),('permits',self.permits)]:
                if selected not in {'all','development',name}: continue
                self.current=name
                try: result=fn()
                except Exception as e: result={'status':'failed','results':[],'error':str(e)}
                self.store.record_scan(name,result)
        finally:
            self.current='';self.running=False;self.last_finished=time.time()
    def status(self): return {'running':self.running,'current':self.current,'sources':self.store.health(),'newsSources':[s['id'] for s in self.sources],'sourceNames':{s['id']:s['name'] for s in self.sources},'version':VERSION,'communityId':self.community_id}
    def loop(self):
        last_backup=''
        while not self.stop.wait(30):
            try:
                day=dt.date.today().isoformat()
                if last_backup!=day and self.store.workspace()['state'] is not None:
                    self.store.backup();last_backup=day
                settings=self.store.settings()
                if settings.get('enabled') and (self.last_finished is None or time.time()-self.last_finished>int(settings.get('intervalMinutes',180))*60): self.trigger()
            except Exception:
                # Scheduler remains alive; operational failures are recorded as source health.
                import logging;logging.exception('Scheduled check failed')
