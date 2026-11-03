import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from storage import Store
from deed_matching import rank_record
from community_sources import parse_classes
import plat_service
import neighborops_server as permits

class FreshScanTests(unittest.TestCase):
    def test_failure_and_running_move_old_findings_to_history(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);s.record_scan('plats',{'status':'success','results':[{'externalKey':'p','title':'Current'}]})
            self.assertTrue(s.findings()[0]['verifiedInLatestScan'])
            for state in ('running','failed'):
                s.record_scan('plats',{'status':state,'results':[]})
                self.assertFalse(s.findings()[0]['verifiedInLatestScan'])
                self.assertEqual(s.findings()[0]['title'],'Current')
    def test_new_check_does_not_recycle_missing_record(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);a={'externalKey':'a','title':'A'};b={'externalKey':'b','title':'B'}
            s.record_scan('news',{'status':'success','results':[a,b]})
            s.record_scan('news',{'status':'success','results':[a]})
            rows={r['externalKey']:r for r in s.findings()}
            self.assertTrue(rows['a']['verifiedInLatestScan']);self.assertEqual(rows['a']['changeType'],'unchanged')
            self.assertFalse(rows['a']['freshNews'])
            self.assertFalse(rows['b']['verifiedInLatestScan'])
    def test_only_material_changes_make_saved_news_fresh_again(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);item={'externalKey':'news:a','title':'Community workshop','summary':'At the library','publishedAt':'2026-10-29T09:00:00-05:00'}
            s.record_scan('news',{'status':'success','results':[item]})
            self.assertTrue(s.findings()[0]['freshNews'])
            s.record_scan('news',{'status':'success','results':[{**item,'retrievedAt':'later','sourceUpdatedAt':'later'}]})
            self.assertFalse(s.findings()[0]['freshNews'])
            s.record_scan('news',{'status':'success','results':[{**item,'summary':'Venue changed to community center'}]})
            self.assertTrue(s.findings()[0]['freshNews']);self.assertEqual(s.findings()[0]['changeType'],'updated')
            s.record_scan('news',{'status':'failed','results':[]})
            self.assertFalse(s.findings()[0]['freshNews'])
    def test_cache_never_inserts_fresh_findings(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d)
            for mode in ('cache','live_archive'):
                s.record_scan('plats',{'status':'success','sourceMode':mode,'results':[{'externalKey':'old'}]})
            self.assertEqual(s.findings(),[])
    def test_offline_scan_never_opens_packaged_cache(self):
        with tempfile.TemporaryDirectory() as d,patch('public_plats.scan_public',side_effect=OSError('offline')),patch.object(plat_service,'cached_snapshot',side_effect=AssertionError('cache read')):
            r=plat_service.scan_plats(root=Path(d),fetch=lambda url:(_ for _ in ()).throw(OSError('offline')))
            self.assertEqual(r['status'],'failed');self.assertEqual(r['results'],[])
    def test_old_live_download_is_not_current(self):
        with tempfile.TemporaryDirectory() as d,patch('public_plats.scan_public',side_effect=OSError('login')):
            r=plat_service.scan_plats(root=Path(d),fetch=lambda url:b'<a href="Plat-Current-Agenda-Spreadsheet-07-09-2026.xlsx">old</a>')
            self.assertEqual(r['status'],'failed');self.assertEqual(r['results'],[])

class DeedMatchingTests(unittest.TestCase):
    def setUp(self):self.prop={'searchName':'OAK FOREST','section':'1','lot':'19','block':'16'}
    def rank(self,**legal):return rank_record({'legalDescriptions':[legal],'grantees':['OAK FOREST SECTION 1']},self.prop)['scope']
    def test_similar_subdivision_never_matches(self):self.assertEqual(self.rank(subdivision='GROVE AT OAK FOREST',section='1',lot='1-36'),'other-subdivision')
    def test_missing_name_does_not_borrow_grantee(self):self.assertEqual(self.rank(section='1',lot='19',block='16'),'section-unknown')
    def test_exact_lot_range(self):self.assertEqual(self.rank(subdivision='OAK FOREST',section='1',lot='1-36',block='16'),'lot')
    def test_wrong_block(self):self.assertEqual(self.rank(subdivision='OAK FOREST',section='1',lot='19',block='2'),'other-lot')
    def test_same_section_different_subdivision(self):self.assertEqual(self.rank(subdivision='OAK FOREST ESTATES',section='1'),'other-subdivision')
    def test_exact_section(self):self.assertEqual(self.rank(subdivision='OAK FOREST',section='1'),'section')

class ClassesTests(unittest.TestCase):
    def test_expired_and_upcoming_classes_are_separate(self):
        raw=b'<h3>Available Classes &amp; Workshops</h3><div class="info"><h5>Past class</h5>10/24/2026 10:00 AM</div><div class="info"><h5>Homebuyer Education</h5>11/7/2026 7:30 AM Free</div>'
        r=parse_classes(raw,{'name':'CRC','url':'https://fwcrc.my.site.com/'},now=dt.datetime(2026,10,29,tzinfo=dt.timezone.utc))
        self.assertEqual([x['title'] for x in r['results']],['Homebuyer Education'])
        self.assertIsNone(r['results'][0]['publishedAt']);self.assertEqual(r['sourceMode'],'public_calendar')
    def test_layout_change_is_failure_not_empty_success(self):
        with self.assertRaises(ValueError):parse_classes(b'<p>Sign in</p>',{'name':'CRC','url':'https://fwcrc.my.site.com/'})

if __name__=='__main__':unittest.main()
