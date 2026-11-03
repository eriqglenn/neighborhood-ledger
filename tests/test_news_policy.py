import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from collectors import parse_feed,SOURCES
from news_policy import classify,POLICY

CASES=[
 ('Fifth Ward food giveaway','','giveaways'),
 ('HPD hosts free backpack giveaway','','giveaways'),
 ('Fifth Ward art and book swap','','giveaways'),
 ('Fifth Ward community resource fair','','events'),
 ('Crime prevention workshop in Fifth Ward','','events'),
 ('Fifth Ward homebuyer assistance','','resources'),
 ('Public hearing on Fifth Ward road closure','','civic'),
 ('Boil water notice for Houston','','civic'),
 ('Man arrested after stabbing at food giveaway','Community event','crime'),
 ('Fatal shooting in Fifth Ward','Workshop was nearby','crime'),
 ('Community workshop','Officials discussed previous shootings.','events'),
 ('Fifth Ward investigation','Police arrested a suspect after the shooting.','crime'),
 ('Fifth Ward resourcefulness','','other'),
]

class NewsPolicyTests(unittest.TestCase):
    def test_topics_and_crime_precedence(self):
        for title,summary,expected in CASES:
            with self.subTest(title=title):self.assertEqual(classify(title,summary),expected)

    def test_existing_frontend_records_use_same_rules(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node not installed')
        source=(Path(__file__).resolve().parents[1]/'app/office.js').read_text(encoding='utf-8')
        function=source[source.index('function newsTopic('):source.index('function communityNews(')]
        script='const newsPolicy='+json.dumps(POLICY)+';'+function+';console.log(JSON.stringify('+json.dumps(CASES)+'.map(([title,summary])=>newsTopic({title,summary}))));'
        result=subprocess.run([node,'-e',script],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),[c[2] for c in CASES])

    def test_feed_ranks_community_first_and_retains_source_dates(self):
        raw=b'''<rss><channel><item><title>Fatal shooting in Fifth Ward</title><link>https://www.houstonpublicmedia.org/crime</link><pubDate>Sat, 26 Sep 2026 12:00:00 GMT</pubDate></item><item><title>Fifth Ward food giveaway</title><link>https://www.houstonpublicmedia.org/food</link><pubDate>Fri, 25 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>'''
        d=parse_feed(raw,SOURCES[1],now=dt.datetime(2026,9,27,tzinfo=dt.timezone.utc))
        self.assertEqual([r['newsTopic'] for r in d['results']],['giveaways','crime'])
        self.assertEqual(d['counts']['routineCrime'],1)
        self.assertEqual(d['counts']['communityUpdates'],1)
        self.assertTrue(d['results'][0]['publishedAt'].startswith('2026-09-25'))
        self.assertNotIn('eventDate',d['results'][0])
        self.assertEqual(d['results'][0]['geographyStatus'],'review_required')

    def test_community_words_do_not_bypass_dates_or_geography(self):
        template='<rss><channel><item><title>{}</title><link>https://www.houstonpublicmedia.org/test</link><pubDate>{}</pubDate></item></channel></rss>'
        now=dt.datetime(2026,9,27,tzinfo=dt.timezone.utc)
        for title,date in [('Fifth Ward giveaway',''),('Fifth Ward giveaway','Mon, 01 Jun 2026 12:00:00 GMT'),('Another neighborhood giveaway','Sat, 26 Sep 2026 12:00:00 GMT')]:
            self.assertEqual(parse_feed(template.format(title,date).encode(),SOURCES[1],now=now)['results'],[])
