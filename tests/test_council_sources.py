import datetime as dt
import json
import tempfile
import unittest
from unittest.mock import patch
from communities import PROFILES,selected,profile
from council_sources import sources_for_districts,fetch_district,parse_district,dated,canonical_link,calendar_urls
from deed_search import Tree
from collectors import sources_for_community
from storage import Store
from monitor import Monitor

NOW=dt.datetime(2026,10,29,12,tzinfo=dt.timezone.utc)
def source(d='B',kind='news'):
    return {'id':f'district-{d.lower()}-{kind}','district':d,'kind':kind,'name':f'District {d} updates','url':f'https://www.houstontx.gov/council/{d.lower()}/','format':'council'}
def bundle(html='',errors=None,calendars=None):
    return json.dumps({'pages':[{'url':source()['url'],'html':html}],'errors':errors or [],'calendars':calendars or []}).encode()
def link(label,url='https://mailchi.mp/council/update'):return '<li><a href="'+url+'">'+label+'</a></li>'
ICAL='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Ledger//EN\r\nBEGIN:VEVENT\r\nUID:community-fair\r\nDTSTART;VALUE=DATE:20261101\r\nDTEND;VALUE=DATE:20261102\r\nSUMMARY:Community resource fair\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'

class CouncilTests(unittest.TestCase):
    def test_all_88_mappings_and_split_districts(self):
        self.assertEqual(len(PROFILES),88)
        self.assertEqual(sum(len(p['councilDistricts']) for p in PROFILES.values()),137)
        for ident in PROFILES:
            with selected(ident):
                districts=profile()['councilDistricts'];self.assertTrue(districts)
                self.assertTrue(set(districts)<=set('ABCDEFGHIJK'))
                sources=sources_for_districts();self.assertEqual(len(sources),len(districts)*2)
                self.assertEqual({s['district'] for s in sources},set(districts))
        for ident,expected in [('55',['B','H']),('25',['F','J']),('15',['C','H']),('6',['B','C','H']),('80',['D','E','I'])]:
            self.assertEqual(profile(ident)['councilDistricts'],expected)

    def test_fifth_ward_has_one_b_calendar_and_h_news(self):
        with selected('55'):
            ids=[s['id'] for s in sources_for_community()]
            self.assertEqual(ids.count('district-b-calendar'),1);self.assertIn('district-h-news',ids)
        with selected('25'):
            self.assertNotIn('district-b-calendar',[s['id'] for s in sources_for_community()])

    def test_current_dated_news_no_keyword_filter(self):
        with selected('55'):
            result=parse_district(bundle(link('October 20, 2026 — District B town hall')),source(),now=NOW)
        self.assertEqual(result['status'],'success');self.assertEqual(len(result['results']),1)
        row=result['results'][0];self.assertEqual(row['publishedAt'],'2026-10-20')
        self.assertEqual(row['councilDistrict'],'B');self.assertEqual(row['geographyScope'],'districtwide')

    def test_old_undated_future_and_archived_not_fresh(self):
        for label in ['January 1, 2020 old news','November 20, 2026 future','Latest newsletter']:
            self.assertEqual(parse_district(bundle(link(label)),source(),now=NOW)['results'],[])
        self.assertEqual(parse_district(bundle('This page is archived'+link('October 20, 2026')),source(),now=NOW)['results'],[])

    def test_month_precision_without_inventing_day(self):
        row=parse_district(bundle(link('October 2026')),source(),now=NOW)['results'][0]
        self.assertEqual(row['publishedAt'],'2026-10');self.assertEqual(row['publicationPrecision'],'month')
        self.assertEqual(parse_district(bundle(link('September 2026')),source(),now=NOW)['results'],[])
        self.assertEqual(dated('Feb. 24, 2026')[1],'2026-02-24')

    def test_tracking_dedup_and_conflicting_old_date(self):
        a='https://mailchi.mp/council/one?e=recipient&utm_source=mail';b='https://mailchi.mp/council/one'
        html=link('October 12, 2026',a)+link('October 12, 2026',b)
        rows=parse_district(bundle(html),source(),now=NOW)['results'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['url'],b)
        self.assertEqual(parse_district(bundle(html+link('January 1, 2020',b)),source(),now=NOW)['results'],[])
        self.assertNotEqual(canonical_link('https://myemail.constantcontact.com/update?aid=1&soid=2'),canonical_link('https://myemail.constantcontact.com/update?aid=3&soid=2'))

    def test_unsafe_links_and_subscriptions_excluded(self):
        for url in ['javascript:alert(1)','https://evil.example/update','https://user@houstontx.gov/council/b/test','https://mailchi.mp/council/signup']:
            self.assertEqual(parse_district(bundle(link('October 20, 2026',url)),source(),now=NOW)['results'],[])

    def test_calendar_discovery_and_all_district_occurrences(self):
        html='<iframe src="https://calendar.google.com/calendar/embed?src=abc%40gmail.com"></iframe><iframe src="https://outlook.office365.com/owa/calendar/public/id/calendar.html"></iframe>'
        urls=calendar_urls(Tree(html));self.assertEqual(urls,['https://calendar.google.com/calendar/ical/abc%40gmail.com/public/basic.ics','https://outlook.office365.com/owa/calendar/public/id/calendar.ics'])
        result=parse_district(bundle(calendars=[{'url':urls[0],'page':source()['url'],'ical':ICAL}]),source(kind='calendar'),now=NOW)
        self.assertEqual(len(result['results']),1);self.assertTrue(result['complete'])
        self.assertIsNone(result['results'][0]['publishedAt']);self.assertEqual(result['results'][0]['geographyScope'],'districtwide')

    def test_failed_calendar_does_not_retire_saved_occurrence(self):
        s=source(kind='calendar')
        with tempfile.TemporaryDirectory() as root:
            store=Store(root)
            good=parse_district(bundle(calendars=[{'url':'https://calendar.google.com/test.ics','page':s['url'],'ical':ICAL}]),s,now=NOW)
            store.record_scan(s['id'],good)
            failed=parse_district(bundle(errors=[{'url':s['url'],'error':'Blocked'}]),s,now=NOW)
            store.record_scan(s['id'],failed);row=store.findings()[0]
            self.assertTrue(row['onCurrentCalendar']);self.assertFalse(row['verifiedInLatestScan'])
            empty=parse_district(bundle(calendars=[{'url':'https://calendar.google.com/test.ics','page':s['url'],'ical':'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n'}]),s,now=NOW)
            store.record_scan(s['id'],empty);self.assertFalse(store.findings()[0]['onCurrentCalendar'])

    def test_partial_keeps_only_successful_live_evidence(self):
        report=parse_district(bundle(link('October 20, 2026'),errors=[{'url':source()['url']+'press.html','error':'Blocked'}]),source(),now=NOW)
        self.assertEqual(report['status'],'partial');self.assertEqual(len(report['results']),1)
        self.assertIn('Blocked',' '.join(report['warnings']))

    def test_discovery_follows_district_only_and_preserves_failures(self):
        visited=[]
        def fetch(url):
            visited.append(url)
            if url.endswith('announcements.html'):raise OSError('Network blocked')
            return 'District B'+link('Newsletters',source()['url']+'news.html')+link('Announcements',source()['url']+'announcements.html')+link('Newsletters','https://evil.example/news.html')+link('October 20, 2026')
        raw=fetch_district(source(),fetch=fetch);report=parse_district(raw,source(),now=NOW)
        self.assertEqual(len(visited),3);self.assertTrue(all('/council/b/' in u for u in visited))
        self.assertEqual(report['status'],'partial');self.assertEqual(len(report['results']),1)

    def test_changed_district_identity_fails_visibly(self):
        raw=fetch_district(source(),fetch=lambda url:'District C'+link('October 20, 2026'))
        report=parse_district(raw,source(),now=NOW)
        self.assertEqual(report['status'],'failed');self.assertEqual(report['results'],[])

    def test_monitor_stores_evidence_and_stays_in_selected_community(self):
        with tempfile.TemporaryDirectory() as root,selected('25'):
            store=Store(root);monitor=Monitor(store,None,None);monitor.sources=[source('F')]
            today=dt.datetime.now().strftime('%B %d, %Y')
            with patch('monitor.fetch_district',return_value=bundle(link(today))),patch('monitor.fetch_feed',side_effect=AssertionError('Wrong fetcher')):
                monitor.run('news')
            rows=store.findings();self.assertEqual(len(rows),1);self.assertIn('Alief',rows[0]['location'])
            self.assertEqual(len(list((store.root/'source_evidence').glob('*.json'))),1)
            self.assertIn('district-f-news',monitor.status()['sourceNames'])
