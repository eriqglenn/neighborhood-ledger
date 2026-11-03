"""Public City notices and calendar occurrences; deterministic source attribution."""
import datetime as dt
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
import icalendar
import recurring_ical_events
from news_policy import describe
from communities import profile, keywords as community_keywords

CENTRAL = ZoneInfo('America/Chicago')
WARD = re.compile(r'\b(?:fifth ward|super neighborhood\s*#?\s*55|SN\s*#?\s*55)\b', re.I)

def parse_classes(raw,source,*,now=None,**unused):
    """Read only the organizer's explicitly dated public class cards."""
    from deed_search import Tree
    now=(now or dt.datetime.now(dt.timezone.utc)).astimezone(CENTRAL)
    tree=Tree(raw);results=[];seen=0
    if 'Available Classes & Workshops' not in tree.root.text():raise ValueError('Public class schedule layout changed')
    for node in tree.root.walk():
        if node.tag!='h5' or not node.parent or 'info' not in node.parent.attrs.get('class','').split():continue
        title=node.text();text=node.parent.text();seen+=1
        match=re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\b',text)
        if not match:raise ValueError('A listed class has no recognizable date')
        start=dt.datetime.strptime(match[1]+' '+match[2],'%m/%d/%Y %I:%M %p').replace(tzinfo=CENTRAL)
        if not now<=start<now+dt.timedelta(days=45):continue
        key=hashlib.sha256((title+'|'+start.isoformat()).encode()).hexdigest()[:24]
        results.append({'externalKey':'class:'+key,'type':'event','title':title,'summary':text[match.end():].strip()[:600],
            'source':source['name'],'sourceUrl':source['url'],'url':source['url'],'sourceMode':'public_calendar','onCurrentCalendar':True,
            'publishedAt':None,'date':start.date().isoformat(),'eventDate':start.date().isoformat(),'eventStart':start.isoformat(),
            'eventEnd':start.isoformat(),'eventTime':start.strftime('%H:%M'),'eventTimezone':'America/Chicago','listedTime':match[2],
            'location':'Fifth Ward CRC program — confirm venue, time and registration with the organizer',
            'sourceMethod':'Organizer public class schedule','geographyStatus':'review_required','workflow':'new',**describe(title,kind='event')})
    return {'status':'success','sourceMode':'public_calendar','complete':True,'sourceUrl':source['url'],'results':results,
        'counts':{'seen':seen,'upcoming':len(results)},'coverage':'Dated classes on the organizer’s public schedule in the next 45 days. Not newly published news.',
        'warnings':['Class times and venues require organizer confirmation; no registration was submitted.']}

def plain(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(value or ''))).strip()

def parse_calendar(raw, source, *, now=None, **unused):
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(CENTRAL)
    calendar = icalendar.Calendar.from_ical(raw)
    if calendar.name != 'VCALENDAR': raise ValueError('Expected a public iCalendar calendar')
    masters = calendar.walk('VEVENT')
    if len(masters) > 2500: raise ValueError('Calendar exceeds event limit')
    district=source.get('district')
    relevant=re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(k) for k in community_keywords())+r')(?!\w)',re.I) if district else WARD
    # Official district feeds include every occurrence, labeled districtwide unless the title names this community.
    selected = set()
    recurring = set()
    for e in masters:
        title = plain(e.get('SUMMARY'))
        if district or WARD.search(title) or re.search(r'\bDistrict B\b', title, re.I): selected.add(str(e.get('UID', '')))
        if e.get('RRULE') or e.get('RDATE'): recurring.add(str(e.get('UID', '')))
    calendar.subcomponents = [e for e in calendar.subcomponents if e.name != 'VEVENT' or str(e.get('UID', '')) in selected]
    end = now.date() + dt.timedelta(days=45)
    events = recurring_ical_events.of(calendar).between(now.date(), end)
    if len(events) > 2500: raise ValueError('Calendar exceeds occurrence limit')
    results = []
    for e in events:
        uid = str(e.get('UID', '')); title = plain(e.get('SUMMARY'))
        if not uid or not title or str(e.get('STATUS', '')).upper() == 'CANCELLED': continue
        ward = bool(relevant.search(title))
        if not district and not ward and not re.search(r'\bDistrict B\b', title, re.I): continue
        start = e.decoded('DTSTART'); finish = e.decoded('DTEND', start)
        timed = isinstance(start, dt.datetime)
        if timed:
            if not start.tzinfo: raise ValueError('Calendar has an ambiguous event timezone')
            start = start.astimezone(CENTRAL)
            if isinstance(finish, dt.datetime): finish = finish.astimezone(CENTRAL)
        day = start.date() if timed else start
        if not now.date() <= day < end: continue
        if timed and isinstance(finish, dt.datetime) and finish <= now: continue
        identity = e.decoded('RECURRENCE-ID', start)
        key = hashlib.sha256((uid + '|' + identity.isoformat()).encode()).hexdigest()[:24]
        modified = e.decoded('LAST-MODIFIED', None)
        location = plain(e.get('LOCATION'))
        scope = profile()['name']+' calendar listing — confirm venue' if ward else 'District '+(district or 'B')+' calendar listing'
        results.append({'externalKey':'calendar:'+key, 'type':'event', 'title':title,
            'summary': ('Recurring calendar listing. ' if uid in recurring else 'Calendar listing. ') + 'Confirm the date, time and location with the organizer before attending or sharing.',
            'url':source['page'], 'source':source['name'], 'sourceUrl':source['url'],
            'sourceMode':'public_calendar', 'sourceMethod':'Official public calendar', 'onCurrentCalendar':True,
            'publishedAt':None, 'sourceUpdatedAt':modified.isoformat() if modified else None,
            'eventStart':start.isoformat(), 'eventEnd':finish.isoformat(), 'eventDate':day.isoformat(),
            'eventTime':start.strftime('%H:%M') if timed else '', 'eventTimezone':'America/Chicago',
            'allDay':not timed, 'recurring':uid in recurring, 'date':day.isoformat(),
            'eventLocation':location, 'location':(location+' · ' if location else 'Location not provided · ')+scope,
            'councilDistrict':district or 'B', 'geographyStatus':'review_required', 'geographyScope':'neighborhood' if ward else 'districtwide',
            'provenance':{'calendarUid':uid,'occurrence':identity.isoformat(),'officialListingPage':source['page']},
            'workflow':'new', 'verified':'Not reviewed', **describe(title, kind='event')})
    return {'status':'success','sourceMode':'public_calendar','complete':True,'sourceUrl':source['url'],
        'results':sorted(results,key=lambda r:r['eventStart']), 'counts':{'seen':len(masters),'upcoming':len(results)},
        'coverage':'Next 45 days of the official council calendar. Recurrences are scheduled listings, not newly published news.',
        'warnings':['Confirm recurring dates and locations with the organizer. Calendar listing does not verify a location inside the selected neighborhood.']}

class NoticeRows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.link=None
    def handle_starttag(self, tag, attrs):
        if tag=='tr': self.row={'text':[], 'links':[]}
        if tag=='a' and self.row is not None:
            self.link=[dict(attrs).get('href',''),[]]; self.row['links'].append(self.link)
    def handle_data(self, text):
        if self.row is not None: self.row['text'].append(text)
        if self.link is not None: self.link[1].append(text)
    def handle_endtag(self, tag):
        if tag=='a': self.link=None
        if tag=='tr' and self.row is not None: self.rows.append(self.row);self.row=None

def parse_notices(raw, source, *, now=None, days=30, **unused):
    now=(now or dt.datetime.now(dt.timezone.utc)).astimezone(CENTRAL)
    parser=NoticeRows();parser.feed(raw.decode('utf-8',errors='replace'))
    results=[]; dates=[]
    for row in parser.rows:
        match=re.search(r'\b[A-Z][a-z]+ \d{1,2}, \d{4}\b', plain(' '.join(row['text'])))
        if not match: continue
        try: day=dt.datetime.strptime(match[0],'%B %d, %Y').date()
        except ValueError: continue
        if day>now.date(): continue
        for href, label in row['links']:
            link=urljoin(source['url'],href);url=urlsplit(link);title=plain(' '.join(label))
            if url.scheme!='https' or url.hostname!='www.houstontx.gov' or url.username or url.password or not re.fullmatch(r'/citizensnet/\d{4}/[^/]+\.html',url.path): continue
            dates.append(day)
            if not title or (now.date()-day).days>days: continue
            results.append({'externalKey':'news:'+hashlib.sha256(link.encode()).hexdigest()[:24],
                'type':'government','title':title,'summary':'Official City notice. Read the original for eligibility, dates and details.',
                'url':link,'source':source['name'],'sourceUrl':source['url'],'publishedAt':day.isoformat(),'date':day.isoformat(),
                'sourceMethod':'Official dated notice index','location':'Citywide — review local applicability','geographyStatus':'review_required',
                'workflow':'new','verified':'Not reviewed',**describe(title)})
    if not dates: raise ValueError('No dated official notices found in the archive')
    stale=(now.date()-max(dates)).days>days
    return {'status':'stale' if stale else 'success','sourceUrl':source['url'],'results':results,'latestPublication':max(dates).isoformat(),
        'coverage':'Dated notices in the City CitizensNet public index; citywide applicability requires review.',
        'warnings':['The public index has no recent dated notices. Older notices were excluded.'] if stale else []}
