import concurrent.futures
import datetime as dt
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from communities import profile, selected, data_root, PROFILES
from storage import Store
from monitor import Monitor
from collectors import sources_for_community, parse_feed
from geography import validate_feature, contains
from public_plats import parse_record
from office_server import create_server
import neighborops_server as legacy

def feature(ident):
    return {'type':'Feature','properties':{'POLYID':int(ident),'SNBNAME':profile(ident)['officialName']},'geometry':{'type':'Polygon','coordinates':[[[-95.4,29.7],[-95.3,29.7],[-95.3,29.8],[-95.4,29.8],[-95.4,29.7]]]}}

class CommunityTests(unittest.TestCase):
    def test_official_catalog_and_validation(self):
        self.assertEqual(len(PROFILES),88)
        self.assertIn('Lazybrook',profile('14')['aliases'])
        self.assertIn('Timbergrove',profile('14')['aliases'])
        self.assertIn('Kingwood',profile('43')['aliases'])
        for ident in PROFILES:
            with selected(ident):
                self.assertTrue(contains(-95.35,29.75,feature(ident)))
                other=feature('55' if ident!='55' else '15')
                with self.assertRaises(ValueError):validate_feature(other)
        for invalid in ('../55','0','89','015','55 OR 1=1'):
            with self.assertRaises(ValueError):profile(invalid)

    def test_legacy_database_is_retained_and_other_workspaces_are_empty(self):
        with tempfile.TemporaryDirectory() as root:
            original=Store(root);state={'version':2,'tasks':[{'title':'Fifth Ward work'}]}
            original.save(state,0)
            with selected('15'):
                other=Store(data_root(root));self.assertIsNone(other.workspace()['state'])
                other.save({'version':2,'communityId':'15','tasks':[{'title':'Heights work'}]},0)
                self.assertNotIn('Fifth Ward',str(other.settings()))
                with self.assertRaises(ValueError):other.save(state,1)
            self.assertEqual(original.workspace()['state'],state)
            self.assertEqual(original.path,Path(root)/'office.sqlite3')

    def test_backup_cannot_restore_another_community(self):
        with tempfile.TemporaryDirectory() as root:
            original=Store(root);original.save({'version':2,'tasks':[]},0);name=original.backup()
            with selected('15'):
                other=Store(data_root(root));(other.root/'backups').mkdir()
                shutil.copy2(Path(root)/'backups'/name,other.root/'backups'/name)
                with self.assertRaises(ValueError):other.restore(name)
                self.assertIsNone(other.workspace()['state'])

    def test_news_source_queries_and_matching_follow_selection(self):
        now=dt.datetime.now(dt.timezone.utc)
        raw=('<rss><channel>'+''.join('<item><title>'+t+'</title><link>https://news.google.com/articles/'+str(i)+'</link><pubDate>'+now.strftime('%a, %d %b %Y %H:%M:%S GMT')+'</pubDate></item>' for i,t in enumerate(['Alief library event','Fifth Ward workshop','Houston city meeting']))+'</channel></rss>').encode()
        with selected('25'):
            sources=sources_for_community();self.assertFalse(any(s['id'] in {'crc-classes','district-b-calendar'} for s in sources))
            src=sources[0];self.assertIn('Alief',src['url']);self.assertNotIn('Fifth',src['url'])
            self.assertEqual([r['title'] for r in parse_feed(raw,src,now=now)['results']],['Alief library event'])
        with selected('55'):self.assertTrue(any(s['id']=='crc-classes' for s in sources_for_community()))

    def test_plat_exact_selected_membership(self):
        now=dt.datetime.now(dt.timezone.utc)
        def row(name):return {'EntityName':'pt_application','Attributes':[{'Name':k,'DisplayValue':v} for k,v in {'pt_superneighborhoodtext':name,'pt_name':'2026-123','pt_fullsubname_reformatted':'A plat','ab.pt_cycleenddate':now.isoformat()}.items()]}
        with selected('25'):
            self.assertEqual(parse_record(row('ALIEF'),{},now)[0]['location'],'Alief SN 25')
            self.assertIsNone(parse_record(row('GREATER FIFTH WARD'),{},now)[0])
            self.assertIsNone(parse_record(row('ALIEF / OTHER'),{},now)[0])

    def test_permits_parse_zips_outside_fifth_ward(self):
        raw='<table>'+''.join('<tr><td>'+z+'</td><td>2026/10/29</td><td>New</td><td>12345678</td><td>100 Test Street</td><td>New office</td></tr>' for z in ['77020','77008','77072','77339','77489'])+'</table>'
        self.assertEqual({r['zip'] for r in legacy.parse_permit_rows(raw)},{'77020','77008','77072','77339','77489'})

    def test_outline_and_permit_geography_work_outside_fifth_ward(self):
        from plat_locations import verify_outline
        from geography import precise_address
        outline={'type':'Polygon','coordinates':[[[-95.38,29.72],[-95.36,29.72],[-95.36,29.74],[-95.38,29.74],[-95.38,29.72]]]}
        for ident in ['15','25','43']:
            with selected(ident):
                point=verify_outline(outline,feature(ident))
                self.assertTrue(contains(*point,feature(ident)))
        candidate={'score':100,'attributes':{'Addr_type':'PointAddress','City':'Kingwood','Postal':'77339','AddNum':'123','StName':'MAIN'}}
        self.assertTrue(precise_address(candidate,'123 Main Street',zip_code='77339'))
        self.assertFalse(precise_address(candidate,'123 Main Street',zip_code='77008'))

    def test_permit_workers_retain_selected_boundary_and_report_zip(self):
        with tempfile.TemporaryDirectory() as root,selected('25'),patch.object(legacy,'CACHE_FILE',Path(root)/'cache.json'),patch.object(legacy,'get_boundary',return_value=feature('25')):
            date=dt.date.today().strftime('%Y/%m/%d')
            raw=f'<p>From: {date} To: {date}</p><table><tr><th>Zip Code</th><th>Permit Date</th><th>Type</th><th>Project No</th><th>Address</th><th>Description</th></tr><tr><td>77072</td><td>{date}</td><td>NEW</td><td>12345678</td><td>100 Main St</td><td>New office</td></tr></table>'
            def geocode(address,zip_code):
                self.assertEqual(profile()['id'],'25');self.assertEqual(zip_code,'77072')
                return {'lat':29.75,'lng':-95.35,'match':address}
            with patch.object(legacy,'geocode',side_effect=geocode):
                result=legacy.scan_permits(raw)
                self.assertEqual(len(result['results']),1)
                self.assertIn('Alief',result['results'][0]['matchMethod'])

    def test_delayed_scan_keeps_original_community(self):
        with tempfile.TemporaryDirectory() as root,patch.object(Monitor,'start'):
            def scan():
                return {'status':'success','results':[{'externalKey':'same-case','kind':'Plat','title':profile()['name']}]}
            with selected('15'):monitor=Monitor(Store(data_root(root)),scan,scan)
            with selected('25'):
                thread=threading.Thread(target=monitor.run,args=('development',));thread.start();thread.join()
                self.assertEqual(profile()['id'],'25')
            self.assertEqual({r['title'] for r in monitor.store.findings()},{'Greater Heights'})

class CommunityServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.mock=patch.object(Monitor,'start');self.mock.start()
        self.server=create_server(0,self.temp.name);self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.mock.stop();self.temp.cleanup()
    def request(self,path,ident='55',body=None):
        headers={'X-Ledger-Community':ident,'X-Ledger-Token':self.server.token,'Content-Type':'application/json'}
        with urllib.request.urlopen(urllib.request.Request(self.url+path,headers=headers,data=None if body is None else json.dumps(body).encode()),timeout=10) as response:return json.load(response)
    def test_concurrent_requests_never_mix_workspaces_or_findings(self):
        def save(ident):
            self.request('/api/workspace',ident,{'revision':0,'state':{'version':2,'communityId':ident,'tasks':[{'title':ident}]}})
            with selected(ident):self.server.store.record_scan('news',{'status':'success','results':[{'externalKey':'same-url','title':ident}]})
            return self.request('/api/workspace',ident)['state']['tasks'][0]['title']
        with concurrent.futures.ThreadPoolExecutor() as pool:self.assertEqual(list(pool.map(save,['55','15','25'])),['55','15','25'])
        for ident in ['55','15','25']:self.assertEqual(self.request('/api/findings',ident)['results'][0]['title'],ident)
    def test_selection_persists_but_does_not_retarget_old_requests(self):
        self.request('/api/workspace',body={'revision':0,'state':{'version':2,'tasks':[{'title':'Original'}]}})
        self.request('/api/community-selection',body={'id':'25'})
        self.assertEqual(self.request('/api/workspace')['state']['tasks'][0]['title'],'Original')
        with urllib.request.urlopen(self.url+'/') as response:html=response.read().decode()
        self.assertIn('"selected": {"id": "25"',html)
        self.assertIn('communitySelect',html)
        self.assertIsNone(self.request('/api/workspace','25')['state'])
    def test_invalid_and_mismatched_community_rejected(self):
        for ident,body in [('999',None),('15',{'revision':0,'state':{'version':2,'communityId':'55'}})]:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/workspace',ident,body)
            self.assertEqual(caught.exception.code,400);caught.exception.close()
