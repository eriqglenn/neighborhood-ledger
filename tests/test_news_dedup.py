import unittest
from news_dedup import unique_news,group_news,url_key

def row(ident,url,title='Community cleanup planned for this weekend',date='2026-11-02',**extras):return {'id':ident,'url':url,'title':title,'publishedAt':date,**extras}
class NewsDuplicateTests(unittest.TestCase):
 def test_tracking_and_fragment_group_but_keep_originals(self):
  rows=[row('a','https://www.khou.com/article/test?utm_source=rss#top'),row('b','https://khou.com/article/test?fbclid=123')]
  self.assertEqual(len(unique_news(rows)),1);self.assertEqual(len(rows),2);self.assertIn('utm_source',rows[0]['url'])
 def test_google_and_publisher_same_title_same_day_group(self):
  rows=[row('a','https://news.google.com/rss/articles/opaque','Community cleanup planned for this weekend - KHOU'),row('b','https://www.khou.com/article/test')]
  self.assertEqual(len(unique_news(rows)),1)
 def test_different_reporting_and_later_updates_remain(self):
  rows=[row('a','https://abc13.com/story'),row('b','https://khou.com/story'),row('c','https://khou.com/update',date='2026-11-03')]
  self.assertEqual(len(unique_news(rows)),3)
 def test_meaningful_query_parameters_are_preserved(self):
  self.assertNotEqual(url_key('https://example.org/?id=1'),url_key('https://example.org/?id=2'))
 def test_recurring_events_and_different_locations_remain(self):
  rows=[row('a','https://example.org/calendar',eventDate='2026-11-02',location='Park A'),row('b','https://example.org/calendar',eventDate='2026-11-09',location='Park A'),row('c','https://example.org/calendar',eventDate='2026-11-02',location='Park B')]
  self.assertEqual(len(unique_news(rows)),3)
 def test_planning_and_private_records_not_grouped(self):
  rows=[row('a','https://example.org/',kind='Plat'),row('b','https://example.org/',kind='Plat'),row('c','https://example.org/',kind='Saved concern')]
  self.assertEqual(len(unique_news(rows)),3)
 def test_latest_version_represents_same_article(self):
  rows=[row('a','https://example.org/article',date='2026-11-01'),row('b','https://example.org/article',date='2026-11-02')]
  self.assertEqual(unique_news(rows)[0]['id'],'b')
 def test_no_url_short_or_undated_titles_not_grouped(self):
  rows=[row('a','','News',date=''),row('b','','News',date='')]
  self.assertEqual(len(group_news(rows)),2)
 def related_rows(self):
  return [row('a','https://news.google.com/rss/articles/abc','Three hurt, including suspect after chase involving stolen car ends in crash at Sunnyside area business overnight - ABC13 Houston'),row('b','https://news.google.com/rss/articles/khou','3 hurt, including suspect, after chase ends with car crashing into business in Sunnyside area, police say - KHOU')]
 def test_related_coverage_groups_and_preserves_other_outlet(self):
  rows=self.related_rows();result=unique_news(rows)
  self.assertEqual(len(result),1);self.assertEqual(len(result[0]['relatedCoverage']),1)
  self.assertNotIn('relatedCoverage',rows[0])
 def test_changed_counts_and_later_developments_stay_separate(self):
  for changed in ['4 hurt, including suspect, after chase ends with car crashing into business in Sunnyside area, police say - KHOU','3 hurt, including suspect arrested, after chase ends with car crashing into business in Sunnyside area, police say - KHOU']:
   rows=self.related_rows();rows[1]['title']=changed
   self.assertEqual(len(group_news(rows)),2)
 def test_related_coverage_requires_nearby_publication_dates(self):
  rows=self.related_rows();rows[1]['publishedAt']='2026-11-05'
  self.assertEqual(len(group_news(rows)),2)
 def test_related_calendar_occurrences_stay_separate(self):
  rows=self.related_rows()
  for r in rows:r['sourceMode']='public_calendar'
  self.assertEqual(len(group_news(rows)),2)
