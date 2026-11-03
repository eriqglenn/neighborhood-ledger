"""Public parcel identification and County Clerk restriction index lookup.

Index matches are candidates, never a determination of applicability or enforceability.
Uses the v30 plat finder's public WebForms/cookie workflow, without credentials.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import re
import ssl
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import build_opener, HTTPSHandler, HTTPCookieProcessor, HTTPRedirectHandler, Request

PARCEL = 'https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0'
CLERK = 'https://www.cclerk.hctx.net/Applications/WebSearch/RP.aspx'
HOSTS = {'www.cclerk.hctx.net', 'cclerk.hctx.net', 'www.gis.hctx.net'}
FIELDS = 'HCAD_NUM,site_str_num,site_str_num_sfx,site_str_pfx,site_str_name,site_str_sfx,site_str_sfx_dir,site_city,site_zip,legal_dscr_1,legal_dscr_2,legal_dscr_3,legal_dscr_4,tax_year'
LIMITATION = 'These are possible matching recordings, not confirmation that a restriction applies to this property. Review the document, legal description, amendments and releases. No results does not mean unrestricted. Older records may require research with the County Clerk.'

def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()

def now():
    return datetime.now(timezone.utc).isoformat()

def checked_url(value, base=CLERK, clerk_only=False):
    url = urljoin(base, value)
    p = urlsplit(url)
    hosts = HOSTS - {'www.gis.hctx.net'} if clerk_only else HOSTS
    if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
        raise ValueError('The public source returned an unexpected link.')
    return url

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def new_client():
    return build_opener(HTTPSHandler(context=ssl.create_default_context()), HTTPCookieProcessor(CookieJar()), SafeRedirect())

def request(client, url, fields=None):
    url = checked_url(url)
    body = urlencode(fields).encode() if fields is not None else None
    try:
        with client.open(Request(url, data=body, headers={'User-Agent':'NeighborhoodLedger-DeedFinder/13.3'}), timeout=30) as r:
            checked_url(r.url)
            content = r.read(8_000_001)
    except OSError as e:
        host = urlsplit(url).hostname
        service = 'Harris County property-address service' if host == 'www.gis.hctx.net' else 'Harris County Clerk records service'
        reason = e.reason if isinstance(e, URLError) else e
        if isinstance(e, HTTPError):
            detail = f'HTTP {e.code}'
            if e.code == 407: detail += ' — the network proxy requires sign-in'
            elif e.code == 403: detail += ' — access was denied by the service or network'
            elif e.code == 429: detail += ' — the service is limiting requests; wait and retry'
        elif isinstance(reason, ssl.SSLCertVerificationError):
            detail = 'the secure connection certificate could not be verified; ask your IT support to check the connection'
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            detail = 'the connection timed out'
        elif isinstance(reason, socket.gaierror):
            detail = 'the computer could not resolve the service address'
        else:
            detail = 'the connection failed; check internet access or ask IT whether this service is reachable'
        raise ValueError(f'The {service} ({host}) could not be reached: {detail}. This is a connection problem, not a no-match result.') from e
    if len(content) > 8_000_000:
        raise ValueError('The search returned too much data. Narrow the subdivision name on the County website.')
    return content

# A small HTML tree keeps parsing dependency-free in the existing Windows build.
class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []
    def text(self):
        return clean(' '.join(c.text() if isinstance(c, Node) else c for c in self.children))
    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

class Tree(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(content.decode('utf-8', 'replace') if isinstance(content, bytes) else content)
    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in {'input','br','img','meta','link','hr','area','base','embed','param','source','track','wbr'}:
            self.current = node
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)
    def handle_endtag(self, tag):
        n = self.current
        while n.parent:
            if n.tag == tag:
                self.current = n.parent
                return
            n = n.parent
    def handle_data(self, data):
        self.current.children.append(data)

def suffix(nodes, end):
    return next((n for n in nodes if n.attrs.get('id','').endswith(end)), None)

def parse_records(content):
    tree = Tree(content)
    nodes = list(tree.root.walk())
    result = []
    for node in nodes:
        if not node.attrs.get('id','').endswith('_lblFileNo'):
            continue
        row = node.parent
        while row and row.tag != 'tr':
            row = row.parent
        if row is None:
            raise ValueError('The County results layout changed. Search on the County website.')
        parts = list(row.walk())
        def val(end):
            n = suffix(parts, end)
            return n.text() if n else ''
        link = suffix(parts, '_HyperLinkFCEC')
        viewer = checked_url(link.attrs['href'], clerk_only=True) if link and link.attrs.get('href') else ''
        legal = []
        # County rows can contain multiple legal descriptions. Preserve each separately.
        for n in parts:
            if n.attrs.get('id','').endswith('_lblSubDivAdd'):
                prefix = n.attrs['id'][:-len('_lblSubDivAdd')]
                def field(end):
                    z = next((x for x in parts if x.attrs.get('id') == prefix+end), None)
                    return z.text() if z else ''
                legal.append({'subdivision':n.text(), 'section':field('_lblSection'), 'lot':field('_lblLot'), 'block':field('_lblBlock'), 'comment':field('_lblComment')})
        grantees = []
        for n in parts:
            if n.attrs.get('id','').endswith('_lblNames'):
                parent = n.parent
                while parent and parent.tag != 'tr':
                    parent = parent.parent
                if parent and parent.text().startswith('Grantee'):
                    grantees.append(n.text())
        result.append({'fileNumber':node.text(), 'fileDate':val('_lblFileDate'), 'instrumentType':val('_lnkdetailtest'), 'volume':val('_lblVolNo'), 'page':val('_lblPageNo'), 'filmCode':link.text() if link else '', 'pages':val('_lblPgs'), 'grantees':grantees, 'legalDescriptions':legal, 'viewerUrl':viewer})
    text = tree.root.text()
    if not result and not re.search(r'(?:no\s+(?:records|results)|0\s+record|no matching)', text, re.I):
        raise ValueError('The County did not return recognizable results. Open the County search to check.')
    # Do not silently call a first page complete. The UI also always describes scope as index matches.
    limited = bool(re.search(r'(?:maximum|first)\s+\d+\s+(?:records|results)|refine your search', text, re.I))
    for n in nodes:
        if n.tag in {'a','input'} and re.search(r'next|page\$', str(n.attrs), re.I) and 'disabled' not in n.attrs:
            limited = True
    return result, limited

def clerk_search(name, field, kind):
    client = new_client()
    tree = Tree(request(client, CLERK))
    inputs = [n for n in tree.root.walk() if n.tag == 'input' and n.attrs.get('name')]
    names = {n.attrs['name'] for n in inputs}
    prefix = 'ctl00$ContentPlaceHolder1$'
    wanted = prefix + ('txtEE' if field == 'grantee' else 'txtDesc')
    if not {wanted, prefix+'txtInstrument', prefix+'btnSearch'} <= names:
        raise ValueError('The County search form changed. Use the County website to search.')
    fields = {n.attrs['name']:n.attrs.get('value','') for n in inputs if n.attrs.get('type') == 'hidden'}
    fields.update({wanted:name, prefix+'txtInstrument':kind, prefix+'btnSearch':'Search'})
    rows, limited = parse_records(request(client, CLERK, fields))
    return {'records':rows, 'limited':limited, 'field':field, 'type':kind, 'name':name, 'retrievedAt':now()}

WORDS = {'STREET':'ST','AVENUE':'AVE','BOULEVARD':'BLVD','DRIVE':'DR','ROAD':'RD','LANE':'LN','COURT':'CT','PLACE':'PL','CIRCLE':'CIR','PARKWAY':'PKWY','TERRACE':'TER','TRAIL':'TRL','NORTH':'N','SOUTH':'S','EAST':'E','WEST':'W'}
SUFFIXES = {'ST','AVE','BLVD','DR','RD','LN','CT','PL','CIR','PKWY','TER','TRL','WAY','LOOP'}
def canonical(text):
    return ' '.join(WORDS.get(w,w) for w in re.sub(r'[^A-Z0-9 /-]',' ',clean(text).upper()).split())

def address_parts(address):
    text = clean(address).upper()
    if len(text) > 180:
        raise ValueError('Enter a shorter street address.')
    # City/state/ZIP are optional; keep street direction and suffix for matching.
    street = text.split(',')[0]
    # Pasted addresses often omit commas or append a ZIP without a city.
    # Only remove postal fields at the end; preserve street numbers/directions.
    street = re.sub(r'\s+(?:USA|U\.?S\.?A\.?|UNITED STATES(?: OF AMERICA)?)\s*$', '', street)
    postal_tail = bool(re.search(r'\s+(?:TX|TEXAS|\d{5}(?:-\d{4})?)\s*$', street))
    street = re.sub(r'\s+\d{5}(?:-\d{4})?\s*$', '', street)
    street = re.sub(r'\s+(?:TX|TEXAS)\s*$', '', street)
    cities = r'HOUSTON|PASADENA|HUMBLE|KATY|CYPRESS|SPRING|TOMBALL|BELLAIRE|WEST UNIVERSITY PLACE|SOUTH HOUSTON|DEER PARK|BAYTOWN|LA PORTE|JERSEY VILLAGE|SEABROOK|WEBSTER'
    city = re.search(r'\s+(?:'+cities+r')$', street)
    if city:
        candidate = street[:city.start()]
        # Do not turn a street named Houston into an empty street name.
        words = canonical(candidate).split()
        has_name = any(w not in {'N','S','E','W','NE','NW','SE','SW'} for w in words[1:])
        if has_name and (postal_tail or any(w in SUFFIXES for w in words[1:])):
            street = candidate
    street = re.sub(r'\s+(?:APT|UNIT|STE|#)\s*.*$', '', street)
    match = re.fullmatch(r'(\d{1,7})\s+(.+)', canonical(street))
    if not match:
        raise ValueError('Enter a house number and street, such as 1811 Knob Creek Ct, Houston.')
    number, words = int(match[1]), match[2].split()
    if not words:
        raise ValueError('Enter the street name.')
    options = {' '.join(words)}
    if words[0] in {'N','S','E','W','NE','NW','SE','SW'}:
        words = words[1:]; options.add(' '.join(words))
    if words and words[-1] in {'N','S','E','W','NE','NW','SE','SW'}:
        words = words[:-1]; options.add(' '.join(words))
    if words and words[-1] in SUFFIXES:
        options.add(' '.join(words[:-1]))
    options.discard('')
    return number, canonical(street), options

def parcel_query(where, limit=31):
    url = PARCEL+'/query?'+urlencode({'f':'json','where':where,'outFields':FIELDS,'returnGeometry':'false','resultRecordCount':limit})
    try:
        data = json.loads(request(new_client(), url))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError('The Harris County property-address service did not return property data. A service outage or network sign-in/block page may be interfering. This is not a no-match result.') from e
    if not isinstance(data, dict) or data.get('error') or not isinstance(data.get('features'), list):
        raise ValueError('The County parcel service did not return a valid property result.')
    return data

def property_record(a):
    account = clean(a.get('HCAD_NUM'))
    if not re.fullmatch(r'\d{13}', account):
        raise ValueError('The parcel result has an invalid HCAD account.')
    street = clean(' '.join(clean(a.get(k)) for k in ['site_str_num','site_str_num_sfx','site_str_pfx','site_str_name','site_str_sfx','site_str_sfx_dir']))
    legal = [clean(a.get('legal_dscr_'+str(i))) for i in range(1,5)]
    sub = legal[1]
    section = re.search(r'\bSEC(?:TION|T)?\.?\s+(\d+)\b', sub, re.I)
    base = re.split(r'\s+(?:SEC(?:TION|T)?\.?\s+\d|\d+(?:ST|ND|RD|TH)\s+PAR|PAR(?:TIAL)?\s+R/P|R/P\b|REPLAT\b)', sub, maxsplit=1, flags=re.I)[0]
    lot = re.search(r'\bLT\s+([\w/-]+)', legal[0], re.I)
    block = re.search(r'\bBLK\s+([\w/-]+)', legal[0], re.I)
    return {'account':account,'street':street,'address':', '.join(x for x in [street,clean(a.get('site_city')),clean(a.get('site_zip'))] if x),'legalDescription':' · '.join(x for x in legal if x),'subdivision':sub,'searchName':base,'section':section[1] if section else '', 'lot':lot[1] if lot else '', 'block':block[1] if block else '', 'taxYear':clean(a.get('tax_year')), 'sourceUrl':PARCEL, 'retrievedAt':now()}

def find_properties_fields(number, street, zip_code=''):
    number, street, zip_code = clean(number), clean(street), clean(zip_code)
    if not re.fullmatch(r'[0-9]{1,7}', number):
        raise ValueError('Enter a street number using digits only.')
    if not street or len(street)>120 or not re.search(r'[A-Za-z]', street):
        raise ValueError('Enter the street name, including its street type and any direction.')
    return find_properties(f'{number} {street}, Houston, TX', zip_code=zip_code, houston_only=True)

def find_properties(address, zip_code='', houston_only=False):
    zip_code = clean(zip_code)
    if zip_code and not re.fullmatch(r'[0-9]{5}', zip_code):
        raise ValueError('Enter a five-digit ZIP code, or leave ZIP code blank.')
    number, normalized, names = address_parts(address)
    escaped = ','.join("'"+name.replace("'","''")+"'" for name in sorted(names))
    where = f'site_str_num = {number} AND UPPER(site_str_name) IN ({escaped})'
    if houston_only: where += " AND UPPER(site_city) = 'HOUSTON'"
    if zip_code: where += f" AND site_zip = '{zip_code}'"
    data = parcel_query(where)
    results = []
    seen = set()
    for feature in data['features']:
        p = property_record(feature['attributes'])
        if p['account'] in seen:
            continue
        seen.add(p['account'])
        p['exactStreetMatch'] = canonical(p['street']) == normalized
        results.append(p)
    results.sort(key=lambda p:(not p['exactStreetMatch'],p['address'],p['account']))
    return {'query':address,'candidates':results[:30], 'limited':bool(data.get('exceededTransferLimit')) or len(results)>30, 'sourceUrl':PARCEL, 'retrievedAt':now()}

def get_property(account):
    if not isinstance(account,str) or not re.fullmatch(r'\d{13}',account):
        raise ValueError('Choose a property with a valid 13-digit HCAD account.')
    data = parcel_query("HCAD_NUM = '"+account+"'")
    records = [property_record(f['attributes']) for f in data['features']]
    if data.get('exceededTransferLimit') or not records or any(p['account']!=account for p in records):
        raise ValueError('The selected property could not be confirmed. Search the address again.')
    if len({(p['street'],p['legalDescription']) for p in records}) != 1:
        raise ValueError('This account has conflicting parcel descriptions. Check HCAD before selecting it.')
    return records[0]

def search_restrictions(account):
    prop = get_property(account)
    return search_record_index(prop)

def search_subdivision(name, section=''):
    name, section = clean(name).upper(), clean(section)
    if len(name)<3 or len(name)>140 or not re.search(r'[A-Z]', name):
        raise ValueError('Enter a subdivision name between 3 and 140 characters, such as Oak Forest.')
    from deed_matching import NUMBERS
    embedded = re.search(r'\s+SEC(?:TION|T)?\.?\s+(\d{1,3}|'+ '|'.join(NUMBERS) +r')$', name)
    if embedded:
        inferred = NUMBERS.get(embedded[1], embedded[1]).lstrip('0') or '0'
        if section and (section.lstrip('0') or '0') != inferred:
            raise ValueError('The section in the subdivision name differs from the Section field. Use the same section or leave the field blank.')
        section = section or inferred
        name = name[:embedded.start()].strip()
    if len(name)<3 or (section and not re.fullmatch(r'[0-9]{1,3}', section)):
        raise ValueError('Enter the subdivision name and an optional numeric section, such as 1.')
    prop = {'searchName':name,'subdivision':name,'section':section,'lot':'','block':''}
    result = search_record_index(prop)
    result.update(property=None, searchMode='subdivision', subdivision={'name':name,'section':section})
    return result

def search_record_index(prop):
    name = clean(prop['searchName'])
    if len(name)<3 or len(name)>140 or re.match(r'^(?:TR|LT|BLK|ABST)\s',name):
        raise ValueError('A reliable subdivision name was not available for this parcel. Use its legal description on the County website.')
    jobs = [(field,kind) for field in ('grantee','description') for kind in ('RESTR','AMEND')]
    records, searches, errors = {}, [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(clerk_search,name,field,kind) for field,kind in jobs]
        for (field,kind),future in zip(jobs,futures):
            try:
                data = future.result()
                searches.append({k:v for k,v in data.items() if k!='records'})
                for r in data['records']:
                    key = (r['fileNumber'],r['filmCode'])
                    if key not in records:
                        records[key] = {**r,'foundBy':[]}
                    records[key]['foundBy'].append(field+' / '+kind)
            except Exception as e:
                errors.append({'field':field,'type':kind,'message':str(e)})
    rows = list(records.values())
    from deed_matching import rank_record
    for r in rows:
        r['match']=rank_record(r,prop)
        sections = {clean(x['section']).lstrip('0') for x in r['legalDescriptions'] if clean(x['section'])}
        r['sectionNote'] = ('Index includes section '+prop['section']+'; review lot and block' if prop['section'].lstrip('0') in sections else 'Index lists a different section; review carefully') if prop['section'] and sections else 'Section applicability needs document review'
    def order(r):
        try: date = datetime.strptime(r['fileDate'],'%m/%d/%Y').toordinal()
        except ValueError: date = 0
        return (r['match']['rank'],r['instrumentType']!='RESTR',date)
    rows.sort(key=order)
    return {'property':prop,'records':rows,'searches':searches,'errors':errors,'status':'partial' if errors else 'searched', 'sourceUrl':CLERK,'retrievedAt':now(),'limitation':LIMITATION}
