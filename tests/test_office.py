import base64
import copy
import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

from collectors import parse_feed,SOURCES
from geography import validate_feature,contains,select_feature,precise_address
from public_plats import scan_public,FIELDS,PAGE
from plat_ingestion import IngestionError
from storage import Store,Conflict
import neighborops_server as legacy
from office_server import create_server
from monitor import Monitor

NOW=dt.datetime(2026,9,27,12,tzinfo=dt.timezone.utc)
def record(id='1',name='GREATER FIFTH WARD',date='2026-10-01T19:30:00Z'):
    values={'pt_name':'2026-'+id,'pt_fullsubname_reformatted':'Test plat','pt_superneighborhoodtext':name,'ab.pt_cycleenddate':date}
    return {'Id':id,'EntityName':'pt_application','Attributes':[{'Name':k,'DisplayValue':v} for k,v in values.items()]}
def transport(pages):
    layout={'Configuration':{'Id':'public-view','EntityName':'pt_application'},'Columns':[{'LogicalName':k} for k in FIELDS.values()],'Base64SecureConfiguration':'published-server-configuration'}
    encoded=base64.b64encode(json.dumps([layout]).encode()).decode()
    page=f'<div class="entity-grid" data-view-layouts="{encoded}" data-selected-view="public-view" data-get-url="/public-read"></div><div id="antiforgerytoken" data-url="/token"></div>'.encode()
    def fetch(url,body=None,token=None):
        if url==PAGE:return page
        if url.endswith('/token'):return b'<input name="__RequestVerificationToken" value="anonymous-token">'
        assert token=='anonymous-token' and body['search']=='' and body['filter'] is None
        item=pages[body['page']-1]
        if isinstance(item,Exception): raise item
        return json.dumps(item).encode()
    return fetch
def page(rows,number=1,total=None,more=False):return {'Records':rows,'PageNumber':number,'ItemCount':len(rows) if total is None else total,'MoreRecords':more,'NextPagePagingCookie':'next'}

class PublicPlatTests(unittest.TestCase):
    def run_scan(self,pages):
        with tempfile.TemporaryDirectory() as root:return scan_public(root,transport(pages),NOW)
    def test_all_pages_exact_name_only(self):
        result=self.run_scan([page([record('1'),record('2','FIFTH WARD')],total=3,more=True),page([record('3','GREATER FIFTH WARD / OTHER')],number=2,total=3)])
        self.assertEqual(result['totalRows'],3);self.assertEqual(len(result['results']),1);self.assertEqual(len(result['pageHashes']),2)
        self.assertNotIn('lat',result['results'][0]);self.assertEqual(result['results'][0]['provenance'][0]['rawFields']['pt_superneighborhoodtext'],'GREATER FIFTH WARD')
    def test_no_partial_success_on_page_failure(self):
        with self.assertRaises(OSError):self.run_scan([page([record()],total=2,more=True),OSError('offline')])
    def test_repeated_page_rejected(self):
        with self.assertRaises(IngestionError):self.run_scan([page([record()],total=2,more=True),page([record()],number=2,total=2)])
    def test_incomplete_count_rejected(self):
        with self.assertRaises(IngestionError):self.run_scan([page([record()],total=4)])
    def test_count_change_rejected(self):
        with self.assertRaises(IngestionError):self.run_scan([page([record()],total=2,more=True),page([record('2')],number=2,total=3)])
    def test_old_agenda_not_current(self):
        d=self.run_scan([page([record(date='2026-07-09T19:30:00Z')])]);self.assertEqual(d['status'],'partial');self.assertEqual(d['results'],[])
    def test_missing_date_not_today(self):
        d=self.run_scan([page([record(date='')])]);self.assertEqual(d['rejected'][0]['reason'],'invalid_pc_date')
    def test_unexpected_entity_stops(self):
        r=record();r['EntityName']='other'
        with self.assertRaises(IngestionError):self.run_scan([page([r])])
    def test_zero_is_valid_only_when_complete(self):self.assertEqual(self.run_scan([page([])])['results'],[])

def boundary():return {'type':'Feature','properties':{'SNBNAME':'GREATER FIFTH WARD','POLYID':55},'geometry':{'type':'Polygon','coordinates':[[[-95.4,29.7],[-95.3,29.7],[-95.3,29.8],[-95.4,29.8],[-95.4,29.7]],[[-95.37,29.73],[-95.33,29.73],[-95.33,29.77],[-95.37,29.77],[-95.37,29.73]]]}}
class GeographyTests(unittest.TestCase):
    def test_holes_edges_and_outside(self):
        f=boundary();self.assertTrue(contains(-95.39,29.71,f));self.assertFalse(contains(-95.35,29.75,f));self.assertFalse(contains(-95.4,29.75,f));self.assertFalse(contains(-95.37,29.75,f));self.assertFalse(contains(-95.1,29.75,f))
    def test_multipolygon(self):
        f=boundary();f['geometry']={'type':'MultiPolygon','coordinates':[f['geometry']['coordinates']]};self.assertTrue(contains(-95.39,29.71,f))
    def test_unrelated_55_not_identity(self):
        f=boundary();f['properties']={'name':'Fifth Ward','area':55}
        with self.assertRaises(ValueError):validate_feature(f)
    def test_ambiguous_and_truncated_feature_rejected(self):
        with self.assertRaises(ValueError):select_feature({'features':[boundary(),boundary()]})
        with self.assertRaises(ValueError):select_feature({'features':[boundary()],'exceededTransferLimit':True})
    def test_open_ring_rejected(self):
        f=boundary();f['geometry']['coordinates'][0].pop()
        with self.assertRaises(ValueError):validate_feature(f)
    def test_imprecise_addresses_rejected(self):
        c={'score':100,'attributes':{'Addr_type':'PointAddress','City':'Houston','AddNum':'123','StName':'MAIN'}}
        self.assertTrue(precise_address(c,'123 Main St'))
        for attr,value in [('Addr_type','Postal'),('City','Dallas'),('AddNum','125')]:
            bad=copy.deepcopy(c);bad['attributes'][attr]=value;self.assertFalse(precise_address(bad,'123 Main St'))
        self.assertFalse(precise_address(c,'Main and Jones'));c['score']=94;self.assertFalse(precise_address(c,'123 Main St'))
    def test_direction_and_multi_address_ambiguity(self):
        c={'score':100,'attributes':{'Addr_type':'PointAddress','City':'Houston','AddNum':'123','StName':'MAIN','StPreDir':'W'}}
        self.assertFalse(precise_address(c,'123 E Main St'));self.assertTrue(precise_address(c,'123 W Main St'));self.assertFalse(precise_address(c,'123 W Main St A & B'))

class PermitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.cache=patch.object(legacy,'CACHE_FILE',Path(self.temp.name)/'cache.json');self.cache.start()
    def tearDown(self):self.cache.stop();self.temp.cleanup()
    def html(self,date=None):
        date=date or dt.date.today().strftime('%Y/%m/%d')
        return f'<p>From: {date} To: {date}</p><table><tr><th>Zip Code</th><th>Permit Date</th><th>Type</th><th>Project No</th><th>Address</th><th>Description</th></tr><tr><td>77026</td><td>{date}</td><td>NEW</td><td>12345678</td><td>123 MAIN ST</td><td>NEW BUILDING</td></tr></table>'
    def test_permit_provenance_and_boundary(self):
        with patch.object(legacy,'get_boundary',return_value=boundary()),patch.object(legacy,'geocode',return_value={'lat':29.71,'lng':-95.39,'match':'123 Main St'}):
            d=legacy.scan_permits(self.html());self.assertEqual(len(d['results']),1);self.assertEqual(d['results'][0]['provenance']['reportSha256'],d['reportSha256']);self.assertTrue((Path(self.temp.name)/'permit_evidence'/(d['reportSha256']+'.html')).exists())
    def test_zip_inside_hole_rejected(self):
        with patch.object(legacy,'get_boundary',return_value=boundary()),patch.object(legacy,'geocode',return_value={'lat':29.75,'lng':-95.35,'match':'123 Main St'}):
            d=legacy.scan_permits(self.html());self.assertEqual(d['results'],[]);self.assertEqual(d['rejectedCount'],1)
    def test_no_boundary_no_scan(self):
        with patch.object(legacy,'get_boundary',side_effect=ValueError('No official boundary')):
            with self.assertRaises(ValueError):legacy.scan_permits(self.html())
    def test_stale_and_malformed_are_failures(self):
        with patch.object(legacy,'get_boundary',return_value=boundary()):
            with self.assertRaises(RuntimeError):legacy.scan_permits(self.html('2020/01/01'))
            with self.assertRaises(RuntimeError):legacy.scan_permits('<html>Service unavailable</html>')
    def test_deferred_candidates_are_disclosed(self):
        with patch.object(legacy,'get_boundary',return_value=boundary()),patch.object(legacy.time,'monotonic',side_effect=[0,121]):
            d=legacy.scan_permits(self.html());self.assertEqual(d['status'],'partial');self.assertEqual(len(d['deferred']),1)

def feed(date='',title='Fifth Ward notice',extra=''):
    return f'<rss><channel><item><title>{title}</title><link>https://www.houstonpublicmedia.org/test</link><pubDate>{date}</pubDate>{extra}</item></channel></rss>'.encode()
class FeedTests(unittest.TestCase):
    def test_old_excluded_and_stale(self):self.assertEqual(parse_feed(feed('Mon, 01 Jun 2026 12:00:00 GMT'),SOURCES[1],now=NOW)['status'],'stale')
    def test_updated_not_publication(self):self.assertEqual(parse_feed(feed(extra='<updated>2026-09-26T12:00:00Z</updated>'),SOURCES[1],now=NOW)['counts']['undated'],1)
    def test_future_publication_excluded(self):self.assertEqual(parse_feed(feed('Fri, 01 Jan 2027 12:00:00 GMT'),SOURCES[1],now=NOW)['results'],[])
    def test_explicit_keyword_match(self):
        date='Sat, 26 Sep 2026 12:00:00 GMT';self.assertEqual(len(parse_feed(feed(date),SOURCES[1],now=NOW)['results']),1);self.assertEqual(parse_feed(feed(date,'Unrelated article'),SOURCES[1],now=NOW)['results'],[])
    def test_html_error_not_zero_success(self):
        with self.assertRaises(ValueError):parse_feed(b'<html>Service unavailable</html>',SOURCES[0],now=NOW)
    def test_citywide_label(self):
        raw=feed('Sat, 26 Sep 2026 12:00:00 GMT','City budget').replace(b'www.houstonpublicmedia.org',b'cityofhouston.news');d=parse_feed(raw,SOURCES[0],now=NOW);self.assertIn('Citywide',d['results'][0]['location'])

class StorageTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_conflicts_do_not_overwrite(self):
        self.store.save({'version':2,'tasks':[]},0)
        with self.assertRaises(Conflict):self.store.save({'version':2,'tasks':[{'title':'lost'}]},0)
        self.assertEqual(self.store.workspace()['state']['tasks'],[])
    def test_backup_restore_preserves_and_increments(self):
        self.store.save({'version':2,'tasks':[]},0);name=self.store.backup();self.store.save({'version':2,'tasks':[{'title':'new'}]},1);safety=self.store.restore(name);self.assertTrue((Path(self.temp.name)/'backups'/safety).exists());self.assertEqual(self.store.workspace()['revision'],3);self.assertEqual(self.store.workspace()['state']['tasks'],[])
    def test_schema_and_vote_validation(self):
        for bad in [{'version':2,'tasks':['bad']},{'version':1},{'version':2,'office':{'records':[{'title':'Decision','status':'Adopted','kind':'Council decision'}]}}]:
            with self.assertRaises(ValueError):self.store.save(bad,0)
    def test_source_missing_does_not_imply_denial(self):
        self.store.record_scan('plats',{'status':'success','sourceMode':'public_current_agenda','results':[{'externalKey':'plat:1','sourceMode':'public_current_agenda','status':'Listed'}]});self.store.record_scan('plats',{'status':'success','sourceMode':'public_current_agenda','results':[]});r=self.store.findings()[0];self.assertFalse(r['onLatestAgenda']);self.assertEqual(r['status'],'Listed')
    def test_failure_does_not_erase_last_results(self):
        self.store.record_scan('news',{'results':[{'externalKey':'one','title':'One'}]});self.store.record_scan('news',{'status':'failed','results':[]});self.assertEqual(len(self.store.findings()),1)
    def test_invalid_backup_path(self):
        with self.assertRaises(ValueError):self.store.restore('../office.sqlite3')

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.server=create_server(0,self.temp.name);self.url='http://127.0.0.1:'+str(self.server.server_port);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.monitor.stop.set();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        h={'Content-Type':'application/json','X-Ledger-Token':self.server.token};h.update(headers or {});return urllib.request.urlopen(urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=h))
    def test_database_not_publicly_served(self):
        with self.assertRaises(urllib.error.HTTPError) as c:self.request('/office.sqlite3')
        self.assertEqual(c.exception.code,404)
    def test_csrf_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as c:self.request('/api/workspace',{'state':{'version':2},'revision':0},{'X-Ledger-Token':'wrong'})
        self.assertEqual(c.exception.code,403)
    def test_cross_origin_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/backup',{}, {'Origin':'https://unrelated.example'})
    def test_save_and_reopen(self):
        self.request('/api/workspace',{'state':{'version':2,'tasks':[]},'revision':0}).close();d=json.load(self.request('/api/workspace'));self.assertEqual(d['revision'],1)
    def test_html_bootstrap_and_local_assets(self):
        h=self.request('/').read();self.assertNotIn(b'/*OFFICE_TOKEN*/',h);self.assertNotIn(b'/*OFFICE_EXTENSION*/',h);self.assertIn(b'officeForm',h);self.assertEqual(self.request('/vendor/leaflet.js').status,200)

class MonitorTests(unittest.TestCase):
    def test_source_failures_do_not_stop_other_sources(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);m=Monitor(store,lambda:{'status':'success','results':[]},lambda:{'status':'success','results':[]})
            with patch('monitor.fetch_feed',side_effect=OSError('offline')):m.run('all')
            health={r['source']:r['status'] for r in store.health()};self.assertEqual(health['city-news'],'failed');self.assertEqual(health['plats'],'success');self.assertEqual(health['permits'],'success');self.assertFalse(m.running)
    def test_running_check_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as root:
            m=Monitor(Store(root),lambda:None,lambda:None);m.running=True;self.assertFalse(m.trigger('all'))

if __name__=='__main__':unittest.main()
