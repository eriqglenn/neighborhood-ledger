"""Public council indexes and calendars. Every scan fetches live evidence, never a cache.

District membership is the City's 2024 jurisdiction table bundled in communities.json.
Only City district pages authorize discovery; signup forms are never submitted.
"""
import datetime as dt
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from communities import profile
from deed_search import Tree
from community_sources import parse_calendar, CENTRAL
from news_policy import describe

MAPPING_URL='https://www.houstontx.gov/planning/Demographics/sn-jurisdiction-2020/B-SNBR-BY-COUNCIL-DISTRICTS-2024.pdf'
# Public indexes also reachable independently of changing home-page menus.
INDEXES={'a':['newsletters.html'],'d':['newsletter-archive.html'],
 'e':['newsletters.html','press.html'],'f':['newsletter.html','press-releases.html'],
 'g':['newsletters.html'],'i':['announcements.html'],'j':['newsletters-psa-archives.html','psa.html'],
 'k':['newsletters.html']}
CALENDARS={'e':['calendar.html'],'h':['calendar.html']}
MONTHS={name.lower():i for i,name in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
MONTH_PATTERN='(?:'+'|'.join(MONTHS)+'|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
DATE_RE=re.compile(r'\b('+MONTH_PATTERN+r')\.?\s+(?:(\d{1,2})\s*[,\.]\s*)?(20\d{2})\b',re.I)

def sources_for_districts():
    return [{'id':f'district-{d.lower()}-{kind}','name':f'District {d} '+('newsletters & announcements' if kind=='news' else 'community calendar'),
             'district':d,'kind':kind,'url':f'https://www.houstontx.gov/council/{d.lower()}/',
             'host':'www.houstontx.gov','official':True,'scope':'districtwide','format':'council'}
            for d in profile()['councilDistricts'] for kind in ('news','calendar')]

def allowed(url):
    p=urlsplit(url)
    return p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and p.hostname in {'www.houstontx.gov','houstontx.gov','calendar.google.com','www.google.com','outlook.office365.com','outlook.office.com'}

class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed(newurl):raise ValueError('Council source redirected outside its public publisher')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(url):
    if not allowed(url):raise ValueError('Unexpected council source URL')
    with build_opener(Redirects()).open(Request(url,headers={'User-Agent':'NeighborhoodLedger/13.7 public council reader'}),timeout=15) as r:
        if not allowed(r.url):raise ValueError('Unexpected council source redirect')
        raw=r.read(4_000_001)
    if len(raw)>4_000_000:raise ValueError('Council source exceeds size limit')
    return raw.decode('utf-8-sig','replace')

def local_page(url,district):
    p=urlsplit(url)
    return allowed(url) and p.hostname in {'www.houstontx.gov','houstontx.gov'} and p.path.startswith('/council/'+district.lower()+'/') and not p.query and (p.path.endswith('.html') or p.path.endswith('/'))

def calendar_urls(tree):
    urls=[]
    for n in tree.root.walk():
        if n.tag not in {'iframe','a'}:continue
        url=n.attrs.get('src' if n.tag=='iframe' else 'href','');p=urlsplit(url)
        if not allowed(url):continue
        if p.hostname in {'calendar.google.com','www.google.com'} and p.path=='/calendar/embed':
            for k,value in parse_qsl(p.query):
                if k=='src':urls.append('https://calendar.google.com/calendar/ical/'+quote(value,safe='')+'/public/basic.ics')
        elif p.hostname in {'outlook.office365.com','outlook.office.com'} and p.path.startswith('/owa/calendar/') and p.path.endswith('/calendar.html'):
            urls.append(urlunsplit((p.scheme,p.netloc,p.path[:-5]+'.ics','','')))
        elif p.path.endswith('.ics'):urls.append(url)
    return list(dict.fromkeys(urls))

def fetch_district(source,fetch=download):
    """Bounded discovery; retain each successful response and individual error as evidence."""
    district=source['district'].lower();base=source['url'];kind=source['kind']
    queue=[base]+[urljoin(base,p) for p in (INDEXES if kind=='news' else CALENDARS).get(district,[])]
    pages=[];errors=[];seen=set();feeds={};limit=10
    while queue and len(seen)<limit:
        url=queue.pop(0)
        if url in seen:continue
        seen.add(url)
        try:
            raw=fetch(url);tree=Tree(raw)
            if not re.search(r'\bDistrict\s+'+district+r'\b',tree.root.text(),re.I):raise ValueError('Page no longer identifies this council district')
            pages.append({'url':url,'html':raw})
            if kind=='calendar':
                for feed in calendar_urls(tree):feeds.setdefault(feed,url)
            for n in tree.root.walk():
                if n.tag!='a':continue
                link=urljoin(url,n.attrs.get('href',''));label=n.text()
                pattern=r'newsletter|announc|press.release|newsroom|news archive' if kind=='news' else r'calendar'
                if local_page(link,district) and re.search(pattern,label,re.I) and not re.search(r'sign.?up|subscribe',label,re.I) and link not in seen and link not in queue:queue.append(link)
        except Exception as e:errors.append({'url':url,'error':str(e)})
    if queue:errors.append({'url':base,'error':'Page discovery limit reached; coverage may be incomplete'})
    calendars=[]
    for url,page in list(feeds.items())[:5]:
        try:calendars.append({'url':url,'page':page,'ical':fetch(url)})
        except Exception as e:errors.append({'url':url,'error':str(e)})
    if len(feeds)>5:errors.append({'url':base,'error':'Calendar limit reached; coverage may be incomplete'})
    return json.dumps({'pages':pages,'calendars':calendars,'errors':errors},ensure_ascii=False).encode('utf-8')

def dated(label):
    matches=list(DATE_RE.finditer(label))
    if not matches:return None
    m=matches[-1];month=next((v for k,v in MONTHS.items() if k.startswith(m[1].lower()[:3])),None)
    try:day=dt.date(int(m[3]),month,int(m[2] or 1))
    except (ValueError,TypeError):return None
    return day,day.isoformat() if m[2] else day.strftime('%Y-%m'),'day' if m[2] else 'month'

def canonical_link(url):
    p=urlsplit(url)
    if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password or p.port not in (None,80,443):return None
    host=p.hostname.lower()
    if not (host in {'houstontx.gov','www.houstontx.gov','mailchi.mp','conta.cc','youtu.be','www.youtube.com'} or host.endswith('.constantcontact.com')):return None
    if re.search(r'subscribe|signup|sign-up',p.path,re.I):return None
    # Remove recipient/tracking parameters; retain newsletter identity (aid/soid).
    query=urlencode(sorted((k,v) for k,v in parse_qsl(p.query) if k not in {'e','fbclid','mc_cid','mc_eid'} and not k.startswith('utm_')))
    return urlunsplit(('https',host,p.path,query,''))

def parse_district(raw,source,*,now=None,days=30,**unused):
    now=(now or dt.datetime.now(dt.timezone.utc)).astimezone(CENTRAL);bundle=json.loads(raw)
    pages=bundle['pages'];errors=list(bundle['errors']);rows={};dates=[];counts={'dated':0,'old':0,'future':0,'undated':0};warnings=[]
    district=source['district'];calendar=source['kind']=='calendar';calendar_ok=0;old_links=set()
    if calendar:
        for feed in bundle['calendars']:
            try:
                report=parse_calendar(feed['ical'].encode(),{**source,'url':feed['url'],'page':feed['page']},now=now)
                rows.update((r['externalKey'],r) for r in report['results']);calendar_ok+=1
            except Exception as e:errors.append({'url':feed['url'],'error':str(e)})
        if not bundle['calendars'] and not errors:warnings.append('No readable public calendar feed is linked from the district pages. Events embedded only in flyers or newsletters are not extracted as calendar dates.')
    else:
        for page in pages:
            tree=Tree(page['html'])
            if re.search(r'\bthis page is archived\b',tree.root.text(),re.I):
                warnings.append(page['url']+': the office marks this page as archived.');continue
            for n in tree.root.walk():
                if n.tag!='a':continue
                link=canonical_link(urljoin(page['url'],n.attrs.get('href','')));title=n.text()
                if not link or not title:continue
                stamp=dated(title)
                # Dates outside an anchor are allowed only in its immediate single-link list/paragraph row.
                if not stamp and n.parent and n.parent.tag in {'li','p','tr'} and sum(x.tag=='a' for x in n.parent.walk())==1:stamp=dated(n.parent.text())
                if not stamp:counts['undated']+=1;continue
                date,label,precision=stamp;dates.append(label);counts['dated']+=1
                if date>now.date():counts['future']+=1;continue
                if (now.date()-date).days>days:counts['old']+=1;old_links.add(link);continue
                key='news:'+hashlib.sha256(link.encode()).hexdigest()[:24]
                title=title if re.search('newsletter|telegraph|press|district',title,re.I) else f'District {district}: '+title
                if re.fullmatch(MONTH_PATTERN+r'\s+20\d{2}',n.text(),re.I):title=f'District {district} newsletter — '+n.text()
                summary=f'Official District {district} update. Open the original newsletter or announcement for the full details.'
                policy=describe(title,summary)
                if policy['newsTopic']=='other':policy.update(newsTopic='civic',newsPriority=3)
                record={'externalKey':key,'type':'government','title':title,'summary':summary,'url':link,'source':source['name'],
                    'sourceUrl':page['url'],'publishedAt':label,'date':label,'publicationPrecision':precision,'councilDistrict':district,
                    'sourceMethod':'Live official council dated index','geographyScope':'districtwide','location':f'District {district} — serves part or all of '+profile()['name'],
                    'geographyStatus':'districtwide','workflow':'new',**policy}
                # Conflicting duplicate index dates never make an older edition look newer.
                if key not in rows or rows[key]['publishedAt']>label:rows[key]=record
        rows={key:row for key,row in rows.items() if row['url'] not in old_links}
        if not counts['dated']:warnings.append('No dated public newsletter or announcement entries found. Signup-only, undated, image-only and archived pages are not treated as current news.')
        if counts['old']:warnings.append(f"{counts['old']} older dated entries excluded from the selected {days}-day window.")
    warnings += [e['url']+': '+e['error'] for e in errors]
    status=('partial' if rows or calendar_ok else 'failed') if errors else ('success' if rows or calendar_ok else 'stale' if dates else 'not_posted')
    coverage=(f'Public District {district} calendar occurrences in the next 45 days.' if calendar else f'Live District {district} newsletters and announcements within {days} days. Month-only editions use the beginning of the stated month for age filtering; no publication day is invented.')
    result={'status':status,'sourceUrl':source['url'],'results':list(rows.values()),'coverage':coverage,'warnings':warnings,'counts':counts,
            'latestPublication':max(dates) if dates else None,'councilDistrict':district,'checkedPages':[p['url'] for p in pages],'errors':errors}
    if calendar:result.update(sourceMode='public_calendar',complete=not errors and calendar_ok>0)
    return result
