"""Transactional local office storage. No model services or external database."""
import datetime as dt
import hashlib
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from communities import profile, keywords

def utcnow(): return dt.datetime.now(dt.timezone.utc).isoformat()

class Conflict(ValueError): pass

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

def validate_workspace(value):
    if not isinstance(value,dict) or value.get('version') != 2:
        raise ValueError('Expected a Neighborhood Ledger version 2 workspace')
    for name in ('intelligence','events','tasks','issues','development','projects','grants','sources','audit','residentApplications'):
        if name in value and not isinstance(value[name],list): raise ValueError(name+' must be a list')
        if any(not isinstance(row,dict) for row in value.get(name,[])): raise ValueError(name+' records must be objects')
    for name in ('profile','newsletter','meeting','ceremonial','office'):
        if name in value and not isinstance(value[name],dict): raise ValueError(name+' must be an object')
    if len(json.dumps(value)) > 12_000_000: raise ValueError('Workspace exceeds size limit')
    office=value.get('office',{})
    if not isinstance(office.get('records',[]),list) or not isinstance(office.get('dismissed',[]),list): raise ValueError('Invalid office records')
    for row in office.get('records',[]):
        if not isinstance(row,dict) or not row.get('title'): raise ValueError('Office records require a title')
        if row.get('status')=='Adopted' and (row.get('kind')!='Council decision' or not row.get('meetingDate') or not row.get('vote','').strip()): raise ValueError('Adoption requires a council decision, meeting date and recorded vote / quorum')
    return value

class Store:
    def __init__(self,root):
        self.community_id=profile()["id"]; self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'office.sqlite3'; self.lock=threading.RLock()
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS workspace(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,body TEXT NOT NULL,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,revision INTEGER,body TEXT,changed TEXT,actor TEXT);
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT);
            CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,source TEXT,started TEXT,status TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS findings(key TEXT PRIMARY KEY,source TEXT,first_seen TEXT,last_seen TEXT,changed TEXT,fingerprint TEXT,body TEXT);
            PRAGMA user_version=1;
            ''')
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20,factory=ClosingConnection); c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=20000')
        return c
    def workspace(self):
        with self.lock,self.connect() as c:
            row=c.execute('SELECT * FROM workspace WHERE id=1').fetchone()
            return {'revision':row['revision'],'state':json.loads(row['body'])} if row else {'revision':0,'state':None}
    def save(self,state,revision,actor='Local officer'):
        validate_workspace(state)
        if str(state.get('communityId', '55')) != self.community_id:
            raise ValueError('This workspace belongs to another Super Neighborhood. Switch to that community before importing or saving it.')
        with self.lock,self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM workspace WHERE id=1').fetchone()
            current=old['revision'] if old else 0
            if revision != current: raise Conflict('Records changed in another window. Export your pending work, then reload before saving.')
            if old: c.execute('INSERT INTO history(revision,body,changed,actor) VALUES(?,?,?,?)',(current,old['body'],utcnow(),actor))
            revision=current+1
            c.execute('INSERT OR REPLACE INTO workspace VALUES(1,?,?,?)',(revision,json.dumps(state),utcnow()))
            c.execute('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 300)')
        return revision
    def settings(self,value=None):
        with self.lock,self.connect() as c:
            if value is not None:
                allowed={'enabled','intervalMinutes','days','keywords','autoStart','actor'}
                if set(value)-allowed: raise ValueError('Unknown setting')
                if not 30<=int(value.get('intervalMinutes',180))<=1440: raise ValueError('Interval must be 30–1440 minutes')
                if not 1<=int(value.get('days',30))<=90: raise ValueError('Current feed window must be 1–90 days')
                if not isinstance(value.get('keywords',[]),list) or any(not isinstance(k,str) or len(k)>150 for k in value.get('keywords',[])): raise ValueError('Keywords must be short text strings')
                if len(value.get('keywords',[]))>100: raise ValueError('Too many keywords')
                c.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(value),))
            row=c.execute('SELECT body FROM settings WHERE id=1').fetchone()
            return json.loads(row[0]) if row else {'enabled':False,'intervalMinutes':180,'days':30,'keywords':keywords(self.community_id),'autoStart':False,'actor':'Local officer'}
    def record_scan(self,source,result):
        stamp=utcnow(); ident=uuid.uuid4().hex
        result=dict(result)
        result['communityId']=self.community_id
        # Failed/stale/archive responses cannot insert findings into a fresh scan.
        if result.get('status','success') not in {'success','partial'} or result.get('sourceMode') in {'cache','live_archive'}:
            result['results']=[]
        with self.lock,self.connect() as c:
            if result.get('sourceMode')=='public_current_agenda' and result.get('status')=='success':
                present={r['externalKey'] for r in result.get('results',[])}
                for existing in c.execute("SELECT key,body FROM findings WHERE source='plats'").fetchall():
                    item=json.loads(existing['body'])
                    if existing['key'] not in present and item.get('sourceMode')=='public_current_agenda':
                        item.update(onLatestAgenda=False,agendaCheckedAt=stamp)
                        c.execute('UPDATE findings SET body=? WHERE key=?',(json.dumps(item),existing['key']))
            if result.get('sourceMode')=='public_calendar' and result.get('status')=='success' and result.get('complete') is True:
                present={r['externalKey'] for r in result.get('results',[])}
                for existing in c.execute('SELECT key,body FROM findings WHERE source=?',(source,)).fetchall():
                    item=json.loads(existing['body'])
                    if existing['key'] not in present and item.get('sourceMode')=='public_calendar':
                        item.update(onCurrentCalendar=False,lastCheckedAt=stamp,changedAt=stamp,changeType='updated')
                        c.execute('UPDATE findings SET body=? WHERE key=?',(json.dumps(item),existing['key']))
            for raw in result.get('results',[]):
                if raw.get('sourceMode')=='public_current_agenda': raw={**raw,'onLatestAgenda':True,'agendaCheckedAt':stamp}
                key=raw.get('externalKey') or raw.get('url')
                if not key: continue
                fingerprint=hashlib.sha256(json.dumps({k:raw.get(k) for k in ('title','summary','status','date','publishedAt','eventDate','eventStart','eventEnd','location','url')},sort_keys=True).encode()).hexdigest()
                old=c.execute('SELECT * FROM findings WHERE key=?',(key,)).fetchone()
                changed=stamp if not old or old['fingerprint']!=fingerprint else old['changed']
                item={**raw,'firstSeenAt':old['first_seen'] if old else stamp,'lastCheckedAt':stamp,'changedAt':changed,'changeType':'new' if not old else ('updated' if old['fingerprint']!=fingerprint else 'unchanged')}
                c.execute('INSERT OR REPLACE INTO findings VALUES(?,?,?,?,?,?,?)',(key,source,item['firstSeenAt'],stamp,changed,fingerprint,json.dumps(item)))
            c.execute('INSERT INTO scans VALUES(?,?,?,?,?)',(ident,source,stamp,result.get('status','success'),json.dumps(result)))
        return ident
    def findings(self):
        with self.lock,self.connect() as c:
            latest={}
            for row in c.execute('SELECT id,source,started,status FROM scans ORDER BY started DESC'):
                latest.setdefault(row['source'],dict(row))
            results=[]
            for row in c.execute('SELECT source,last_seen,body FROM findings ORDER BY changed DESC'):
                item=json.loads(row['body']);scan=latest.get(row['source'],{})
                fresh=(scan.get('status') in {'success','partial'} and row['last_seen']==scan.get('started')
                    and item.get('sourceMode') not in {'cache','live_archive','officer_import'} and not row['source'].endswith('-import'))
                item.update(verifiedInLatestScan=fresh,freshNews=fresh and item.get('changeType') in {'new','updated'},scanSource=row['source'],latestScanId=scan.get('id'),latestScanStatus=scan.get('status','unknown'))
                results.append(item)
            return results
    def health(self):
        with self.lock,self.connect() as c:
            rows=c.execute('SELECT * FROM scans ORDER BY started DESC LIMIT 100').fetchall()
            latest={}
            for row in rows:
                if row['source'] not in latest:
                    data=json.loads(row['body']); latest[row['source']]={'source':row['source'],'checkedAt':row['started'],'status':row['status'],'count':len(data.get('results',[])),'warnings':data.get('warnings',[]),'coverage':data.get('coverage',data.get('freshness','')),'error':data.get('error',''),'latestPublication':data.get('latestPublication'),'counts':data.get('counts'),'sourceUrl':data.get('sourceUrl'),'reportStart':data.get('reportStart'),'reportEnd':data.get('reportEnd'),'reportDate':data.get('reportDate')}
            return list(latest.values())
    def backup(self):
        with self.lock:
            folder=self.root/'backups';folder.mkdir(exist_ok=True)
            name=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]+'.sqlite3'
            with self.connect() as source,sqlite3.connect(folder/name,factory=ClosingConnection) as dest: source.backup(dest)
            return name
    def backups(self):
        return [{'name':p.name,'bytes':p.stat().st_size} for p in sorted((self.root/'backups').glob('*.sqlite3'),reverse=True)]
    def restore(self,name):
        if Path(name).name!=name or not name.endswith('.sqlite3'): raise ValueError('Invalid backup name')
        path=self.root/'backups'/name
        if not path.is_file(): raise ValueError('Backup does not exist')
        with self.lock,sqlite3.connect(path,factory=ClosingConnection) as source:
            if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Backup failed integrity check')
            if source.execute('PRAGMA user_version').fetchone()[0]!=1: raise ValueError('Unsupported database version')
            row=source.execute('SELECT body FROM workspace WHERE id=1').fetchone()
            if not row: raise ValueError('Backup has no workspace')
            restored=validate_workspace(json.loads(row[0]))
            if str(restored.get('communityId','55'))!=self.community_id:raise ValueError('This backup belongs to another Super Neighborhood.')
            safety=self.backup(); current=self.workspace()['revision']
            with self.connect() as dest: source.backup(dest)
            with self.connect() as dest: dest.execute('UPDATE workspace SET revision=?,updated=? WHERE id=1',(current+1,utcnow()))
            return safety
