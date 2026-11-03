"""Date-aware RSS/Atom source collection. Explicit text rules; no AI."""
import datetime as dt
import email.utils
import hashlib
import html
import re
import urllib.request
from urllib.parse import urlsplit, urlencode
from communities import profile, keywords as community_keywords
from xml.etree import ElementTree as ET
from news_policy import describe

SOURCES=[
 {'id':'city-news','name':'City of Houston Newsroom','url':'https://cityofhouston.news/feed/','host':'cityofhouston.news','official':True,'scope':'citywide'},
 {'id':'hpm','name':'Houston Public Media','url':'https://www.houstonpublicmedia.org/feed/','host':'houstonpublicmedia.org','official':False,'scope':'neighborhood'},
 {'id':'crc-classes','name':'Fifth Ward CRC classes and workshops','url':'https://fwcrc.my.site.com/Fifthwardcrccft/NWSHOP__TrainingCenterCPS','host':'fwcrc.my.site.com','official':False,'scope':'neighborhood','format':'classes'},
 {'id':'city-community','name':'City of Houston Community News','url':'https://cityofhouston.news/category/community-news/feed/','host':'cityofhouston.news','official':True,'scope':'citywide'},
 {'id':'district-b-calendar','name':'District B community calendar','url':'https://calendar.google.com/calendar/ical/houstondistrictb%40gmail.com/public/basic.ics','page':'https://www.houstontx.gov/council/b/','host':'calendar.google.com','official':True,'scope':'districtwide','format':'ical'},
 {'id':'citizensnet','name':'City CitizensNet notices','url':'https://www.houstontx.gov/citizensnet/','host':'www.houstontx.gov','official':True,'scope':'citywide','format':'html'},
]

def sources_for_community():
    p=profile()
    from council_sources import sources_for_districts
    sources=[dict(s) for s in SOURCES if s['scope']!='districtwide' and (p['id']=='55' or s['id']!='crc-classes')]
    sources.extend(sources_for_districts())
    terms=' OR '.join('"'+name+'"' for name in p['aliases'])
    query='Houston ('+terms+') when:30d'
    sources.insert(0,{'id':'local-news','name':p['name']+' news search','url':'https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'}),'host':'news.google.com','official':False,'scope':'neighborhood'})
    return sources


def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()
def timestamp(raw):
    if not raw: return None
    try: d=email.utils.parsedate_to_datetime(raw)
    except (ValueError,TypeError):
        try: d=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
        except (ValueError,TypeError): return None
    if not d.tzinfo: return None
    return d.astimezone(dt.timezone.utc)

def parse_feed(content,source,*,now=None,days=30,keywords=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    keywords=keywords or community_keywords()
    root=ET.fromstring(content)
    local=lambda tag:tag.rsplit('}',1)[-1]
    if local(root.tag) not in {'rss','feed','RDF'}: raise ValueError('Source is not a supported RSS/Atom feed')
    entries=[e for e in root.iter() if local(e.tag) in {'item','entry'}]
    results=[]; counts={'seen':len(entries),'old':0,'undated':0,'futurePublication':0,'unmatched':0,'badLink':0}
    published_dates=[]
    for item in entries:
        fields={local(e.tag):e for e in item}
        def value(*names):
            for n in names:
                if n in fields: return ''.join(fields[n].itertext())
            return ''
        title=clean(value('title')); excerpt=clean(value('description','summary','content','encoded'))
        link=value('link')
        if not link:
            link=next((e.get('href','') for e in item if local(e.tag)=='link' and e.get('rel','alternate')=='alternate'),'')
        u=urlsplit(link)
        if u.scheme not in {'http','https'} or u.username or u.password or not u.hostname or not (u.hostname==source['host'] or u.hostname.endswith('.'+source['host'])):
            counts['badLink']+=1;continue
        pub=timestamp(value('pubDate','published','date')); updated=timestamp(value('updated','modified'))
        if pub: published_dates.append(pub)
        date=pub  # Retrieval/modification never substitutes for publication.
        if not date: counts['undated']+=1; continue
        if date>now+dt.timedelta(hours=24): counts['futurePublication']+=1;continue
        if now-date>dt.timedelta(days=days): counts['old']+=1;continue
        hay=title+' '+excerpt
        matches=[k for k in keywords if k.strip() and re.search(r'(?<!\w)'+re.escape(k.strip())+r'(?!\w)',hay,re.I)]
        if source['scope']=='neighborhood' and not matches and source['id']!='fifthward-crc': counts['unmatched']+=1;continue
        results.append({'externalKey':'news:'+hashlib.sha256(link.encode()).hexdigest()[:24],'type':'government' if source['official'] else 'resource','title':title,'summary':excerpt[:600],
         'url':link,'source':source['name'],'sourceUrl':source['url'],'publishedAt':date.isoformat(),'sourceUpdatedAt':updated.isoformat() if updated else None,'date':date.date().isoformat(),
         'location':'Citywide — review local applicability' if source['scope']=='citywide' and not matches else profile()['name']+' — location not independently verified',
         'geographyStatus':'review_required','matchedTerms':matches,'sourceMethod':'RSS/Atom publisher excerpt','workflow':'new','verified':'Not reviewed',**describe(title,excerpt)})
    results.sort(key=lambda r:r['newsPriority'])
    counts['routineCrime']=sum(r['newsTopic']=='crime' for r in results)
    counts['communityUpdates']=sum(r['newsTopic'] not in {'crime','other'} for r in results)
    latest=max(published_dates).isoformat() if published_dates else None
    stale=not published_dates or now-max(published_dates)>dt.timedelta(days=days)
    return {'status':'stale' if stale else 'success','sourceUrl':source['url'],'results':results,'counts':counts,'latestPublication':latest,
      'coverage':'Recent items exposed by this publisher feed; not a complete web search','warnings':['Feed has no publication within the selected current window'] if stale else []}

def fetch_feed(source):
    req=urllib.request.Request(source['url'],headers={'User-Agent':'Neighborhood-Ledger/12.2 (public RSS reader)'})
    with urllib.request.urlopen(req,timeout=15) as response:
        host=urlsplit(response.url).hostname or ''
        if not (host==source['host'] or host.endswith('.'+source['host'])): raise ValueError('Feed redirected outside its publisher')
        raw=response.read(4_000_001)
        if len(raw)>4_000_000: raise ValueError('Feed exceeds size limit')
        return raw
