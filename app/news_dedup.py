"""Conservative presentation grouping; original news records and user selections stay intact."""
import re
import unicodedata
import datetime as dt
from urllib.parse import urlsplit,parse_qsl,urlencode

def normalized(value):
    return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()).strip()

def url_key(value):
    try:
        p=urlsplit(value or '')
        if p.scheme not in ('http','https') or not p.hostname:return ''
        host=p.hostname.lower().removeprefix('www.')
        path=re.sub(r'/(amp)/?$','',p.path).rstrip('/') or '/'
        query=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid','mc_cid','mc_eid','oc') and not(k.lower()=='output' and v.lower()=='amp')]
        return host+path+('?' + urlencode(sorted(query)) if query else '')
    except ValueError:return ''

def publisher(value):
    name=normalized(value)
    for marker,alias in [('abc13','abc13'),('khou','khou'),('click2houston','kprc'),('kprc','kprc'),('houston chronicle','chronicle'),('houstonchronicle','chronicle')]:
        if marker in name:return alias
    return name.removesuffix(' com').removesuffix(' org')

def headline_key(row):
    title=str(row.get('title') or '')
    match=re.match(r'^(.*)\s+(?:-|–|—|\|)\s+([^|]+)$',title)
    url=row.get('url') or row.get('sourceUrl') or ''
    host=(urlsplit(url).hostname or '').lower() if url.startswith(('https://','http://')) else ''
    if host=='news.google.com' and match:title,pub=match[1],publisher(match[2])
    else:
        pub=publisher(host.removeprefix('www.') or row.get('source',''))
        if match and publisher(match[2])==pub:title=match[1]
    title=normalized(title);date=str(row.get('eventStart') or row.get('eventDate') or row.get('publishedAt') or row.get('date') or '')[:10]
    return '|'.join((pub,title,date)) if pub and len(title)>=24 and date else ''

def keys(row):
    if row.get('kind') in ('Plat','Permit','Saved concern','Saved follow-up','Live lookup') or row.get('type')=='development':return []
    # Recurring events share URLs: preserve each occurrence and location.
    event='|'+str(row.get('eventStart') or row.get('eventDate') or '')+'|'+normalized(row.get('location')) if row.get('sourceMode')=='public_calendar' or row.get('eventDate') else ''
    url=url_key(row.get('url') or row.get('sourceUrl'));headline=headline_key(row)
    return ([('url',url+event)] if url else [])+([('headline',headline+event)] if headline else [])

def group_news(rows):
    groups=[];index={}
    for row in rows:
        row_keys=keys(row);matches={index[k] for k in row_keys if k in index}
        target=min(matches) if matches else len(groups)
        if not matches:groups.append([])
        for other in matches-{target}:
            groups[target].extend(groups[other]);groups[other]=[]
            for key,value in list(index.items()):
                if value==other:index[key]=target
        groups[target].append(row)
        for key in row_keys:index[key]=target
    groups=[group for group in groups if group]
    parents=list(range(len(groups)));buckets={}
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    for ident,group in enumerate(groups):
        for row in group:
            info=story_signature(row)
            if not info:continue
            day,numbers,stage,words=info
            for delta in (-1,0,1):
                for other,other_words in buckets.get((day+delta,numbers,stage),[]):
                    shared=len(words & other_words)
                    if shared>=6 and shared/len(words|other_words)>=.78:parents[root(ident)]=root(other)
            buckets.setdefault((day,numbers,stage),[]).append((ident,words))
    merged={}
    for ident,group in enumerate(groups):merged.setdefault(root(ident),[]).extend(group)
    return list(merged.values())

STOP=set('a an the in into at on of to for from and or as is are was were with after before including involving ends ended end say says said police houston area overnight vs versus varsity'.split())
STAGES={'updated':'update','updates':'update','arrested':'arrest','arrests':'arrest','charged':'charge','charges':'charge','cancelled':'cancel','canceled':'cancel','rescheduled':'reschedule','postponed':'postpone','approved':'approve','denied':'deny','reopened':'reopen'}
NUMBERS=dict(zip('zero one two three four five six seven eight nine ten'.split(),map(str,range(11))))
def story_signature(row):
    if not keys(row) or row.get('eventDate') or row.get('sourceMode')=='public_calendar':return None
    key=headline_key(row)
    if not key:return None
    title=key.split('|')[1]
    title=re.sub(r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?) \d{1,2} \d{4}\b','',title)
    try:day=dt.date.fromisoformat(key.split('|')[2]).toordinal()
    except ValueError:return None
    words={STAGES.get(word,NUMBERS.get(word,{'crashing':'crash','crashes':'crash','boys':'boy','girls':'girl'}.get(word,word))) for word in title.split() if word not in STOP}
    if len(words)<7:return None
    numbers=tuple(sorted(w for w in words if w.isdigit()));stage=tuple(sorted(words & (set(STAGES.values())|{'update','arrest','charge'})))
    return day,numbers,stage,words

def unique_news(rows):
    def priority(row):return (str(row.get('publishedAt') or row.get('date') or ''),str(row.get('lastCheckedAt') or ''),'news.google.com' not in (row.get('url') or ''),len(str(row.get('summary') or '')))
    result=[]
    for group in group_news(rows):
        chosen=max(group,key=priority);primary=dict(chosen)
        if len(group)>1:primary['relatedCoverage']=[{k:r.get(k,'') for k in ('title','summary','text','url','date','publishedAt')} for r in group if r is not chosen][:5]
        result.append(primary)
    return result
