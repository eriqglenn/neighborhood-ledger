import datetime as dt
import tempfile
import unittest
from collectors import SOURCES
from community_sources import parse_calendar, parse_notices
from storage import Store

NOW=dt.datetime(2026,9,27,12,tzinfo=dt.timezone.utc)
CAL=next(s for s in SOURCES if s['id']=='district-b-calendar')
NOTICES=next(s for s in SOURCES if s['id']=='citizensnet')

def event(extra='',title='SN #55 Fifth Ward Meeting',uid='one'):
    return f'''BEGIN:VEVENT
UID:{uid}
DTSTART;TZID=America/Chicago:20261007T180000
DTEND;TZID=America/Chicago:20261007T190000
SUMMARY:{title}
LAST-MODIFIED:20260401T120000Z
{extra}
END:VEVENT'''

def calendar(*events):
    return ('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Ledger tests//EN\n'+'\n'.join(events)+'\nEND:VCALENDAR').replace('\n','\r\n').encode()

class CalendarTests(unittest.TestCase):
    def parse(self,*events): return parse_calendar(calendar(*events),CAL,now=NOW)
    def test_monthly_dates_and_dst_are_not_new_publications(self):
        rows=self.parse(event('RRULE:FREQ=MONTHLY;BYDAY=1WE'))['results']
        self.assertEqual([r['eventDate'] for r in rows],['2026-10-07','2026-11-04'])
        self.assertTrue(rows[0]['eventStart'].endswith('-05:00'))
        self.assertTrue(rows[1]['eventStart'].endswith('-06:00'))
        self.assertIsNone(rows[0]['publishedAt']);self.assertIn('2026-04-01',rows[0]['sourceUpdatedAt'])
        self.assertTrue(rows[0]['recurring']);self.assertEqual(rows[0]['geographyStatus'],'review_required')
    def test_exdate(self):
        rows=self.parse(event('RRULE:FREQ=MONTHLY;BYDAY=1WE\nEXDATE;TZID=America/Chicago:20261007T180000'))['results']
        self.assertEqual([r['eventDate'] for r in rows],['2026-11-04'])
    def test_cancelled_master_and_ended_series(self):
        self.assertEqual(self.parse(event('STATUS:CANCELLED'))['results'],[])
        self.assertEqual(self.parse(event('RRULE:FREQ=MONTHLY;UNTIL=20260501T000000Z'))['results'],[])
    def test_override_keeps_occurrence_identity(self):
        master=event('RRULE:FREQ=MONTHLY;BYDAY=1WE')
        override=event('RECURRENCE-ID;TZID=America/Chicago:20261007T180000').replace('DTSTART;TZID=America/Chicago:20261007T180000','DTSTART;TZID=America/Chicago:20261008T180000').replace('DTEND;TZID=America/Chicago:20261007T190000','DTEND;TZID=America/Chicago:20261008T190000')
        old=self.parse(master)['results'];new=self.parse(master,override)['results']
        self.assertEqual(new[0]['eventDate'],'2026-10-08');self.assertEqual(old[0]['externalKey'],new[0]['externalKey'])
    def test_cancelled_occurrence(self):
        rows=self.parse(event('RRULE:FREQ=MONTHLY;BYDAY=1WE'),event('RECURRENCE-ID;TZID=America/Chicago:20261007T180000\nSTATUS:CANCELLED'))['results']
        self.assertEqual([r['eventDate'] for r in rows],['2026-11-04'])
    def test_scope_and_all_day(self):
        rows=self.parse(event(title='Acres Homes meeting',uid='other'),event(title='District B resource fair',uid='district'),event(uid='ward').replace('DTSTART;TZID=America/Chicago:20261007T180000','DTSTART;VALUE=DATE:20261007').replace('DTEND;TZID=America/Chicago:20261007T190000','DTEND;VALUE=DATE:20261008'))['results']
        self.assertEqual(len(rows),2);self.assertEqual({r['geographyScope'] for r in rows},{'districtwide','neighborhood'})
        self.assertTrue(next(r for r in rows if r['geographyScope']=='neighborhood')['allDay'])
    def test_invalid_calendar(self):
        with self.assertRaises(ValueError):parse_calendar(b'<html>Service down</html>',CAL,now=NOW)
    def test_failed_scan_retains_events_complete_scan_retires_missing(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);store.record_scan(CAL['id'],self.parse(event()))
            store.record_scan(CAL['id'],{'status':'failed','results':[]})
            self.assertTrue(store.findings()[0]['onCurrentCalendar'])
            store.record_scan(CAL['id'],self.parse())
            self.assertFalse(store.findings()[0]['onCurrentCalendar'])
            self.assertEqual(store.findings()[0]['changeType'],'updated')

class NoticeTests(unittest.TestCase):
    def test_date_and_link_validation(self):
        raw=b'''<table><tr><td>September 26, 2026</td><td><a href="2026/giveaway.html">Free groceries</a></td></tr>
        <tr><td>September 28, 2026</td><td><a href="2026/future.html">Future notice</a></td></tr>
        <tr><td>September 26, 2026</td><td><a href="https://other.example/citizensnet/2026/x.html">Offsite</a></td></tr>
        <tr><td>Unknown</td><td><a href="2026/undated.html">No date</a></td></tr></table>'''
        result=parse_notices(raw,NOTICES,now=NOW)
        self.assertEqual(len(result['results']),1);self.assertEqual(result['results'][0]['newsTopic'],'giveaways')
        self.assertEqual(result['results'][0]['publishedAt'],'2026-09-26')
    def test_stale_index_is_not_recent(self):
        raw=b'<tr><td>November 7, 2025</td><td><a href="2025/event.html">Free meals</a></td></tr>'
        result=parse_notices(raw,NOTICES,now=NOW)
        self.assertEqual(result['status'],'stale');self.assertEqual(result['results'],[])
    def test_changed_structure_fails_visibly(self):
        with self.assertRaises(ValueError):parse_notices(b'<html>No notice index</html>',NOTICES,now=NOW)
