"""Read-only Houston 311 public case search. No login, submissions or cache fallback."""
import base64
import datetime as dt
import http.cookiejar
import json
import re
import socket
import ssl
import urllib.error
from urllib.parse import urljoin,urlsplit,urlencode
from urllib.request import Request,build_opener,HTTPCookieProcessor,HTTPRedirectHandler
from deed_search import Tree

BASE='https://houston311.powerappsportals.us'
PAGE=BASE+'/en-US/checkcasestatus/'

def case_number(value):
    value=str(value or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{3,63}',value) or not re.search(r'\d',value):
        raise ValueError('Enter the complete 311 case number using letters, numbers and hyphens. Do not enter an address, email or wildcard.')
    return value

def official_url(value,base=PAGE):
    url=urljoin(base,value);p=urlsplit(url)
    if p.scheme!='https' or p.hostname!='houston311.powerappsportals.us' or p.username or p.password or p.port not in (None,443):raise ValueError('The 311 portal returned an unexpected link.')
    return url

class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        official_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class Client:
    def __init__(self):self.opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()),Redirects())
    def request(self,url,data=None,token=None):
        headers={'User-Agent':'NeighborhoodLedger/13.7.1 public case status','Referer':PAGE}
        if data is not None:headers.update({'Content-Type':'application/json; charset=utf-8','Accept':'application/json','X-Requested-With':'XMLHttpRequest','__RequestVerificationToken':token})
        with self.opener.open(Request(official_url(url),data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=20) as r:
            official_url(r.url)
            if urlsplit(r.url).path!=urlsplit(url).path:raise ValueError('The 311 portal redirected the lookup. Open the official page to check this case.')
            raw=r.read(3_000_001)
        if len(raw)>3_000_000:raise ValueError('The 311 response exceeded its size limit.')
        return raw

def configuration(raw):
    grids=[n for n in Tree(raw).root.walk() if n.attrs.get('data-view-layouts')]
    if len(grids)!=1:raise ValueError('The 311 search page changed or is unavailable.')
    grid=grids[0];layouts=json.loads(base64.b64decode(grid.attrs['data-view-layouts'],validate=True))
    layout=next((x for x in layouts if x.get('Id')==grid.attrs.get('data-selected-view')),None)
    if not layout or layout['Configuration'].get('EntityName')!='incident' or not layout.get('Base64SecureConfiguration'):raise ValueError('The public case search configuration changed.')
    endpoint=official_url(grid.attrs['data-get-url'])
    if not re.fullmatch(r'/_services/entity-grid-data\.json/[a-f0-9-]{36}',urlsplit(endpoint).path):raise ValueError('Unexpected public case search endpoint.')
    details=official_url(layout['Configuration']['DetailsActionLink']['URL']['PathWithQueryString'])
    if urlsplit(details).path!='/en-US/checkcasestatus/casedetail/':raise ValueError('Unexpected case details page.')
    return endpoint,layout,details

def parse_record(raw,number,details):
    if raw.get('EntityName')!='incident' or not isinstance(raw.get('Attributes'),list):raise ValueError('The public case record format changed.')
    attrs={a['Name']:a.get('DisplayValue','') for a in raw['Attributes']}
    if len(attrs)!=len(raw['Attributes']):raise ValueError('The public case record contains duplicate fields.')
    # Portal search also searches addresses/email and can return partial matches.
    # Accept only the full supplied primary or alternate case number.
    numbers=[str(attrs.get(k,'')).strip().upper() for k in ('coh_casenumber','coh_alternatecasenumber')]
    if number not in numbers:return None
    ident=raw.get('Id','')
    if not re.fullmatch(r'[a-fA-F0-9-]{36}',ident):raise ValueError('The public case record has no valid detail identifier.')
    status=str(attrs.get('statuscode') or '').strip()
    if not status:raise ValueError('The City returned the case without a readable status.')
    # Deliberately exclude resident names, contact details and raw portal attributes.
    return {'caseNumber':str(attrs.get('coh_casenumber') or number),'alternateCaseNumber':str(attrs.get('coh_alternatecasenumber') or ''),
        'serviceType':str(attrs.get('ava_servicerequesttypeid') or ''),'address':str(attrs.get('ava_addressline') or ''),
        'cityStatus':status,'createdAt':str(attrs.get('createdon') or ''),'url':details+'?'+urlencode({'id':ident})}

def lookup(value,client=None):
    number=case_number(value);checked=dt.datetime.now(dt.timezone.utc).isoformat()
    base={'caseNumber':number,'checkedAt':checked,'sourceUrl':PAGE+'?'+urlencode({'query':number})}
    client=client or Client()
    try:
        endpoint,layout,details=configuration(client.request(PAGE))
        token=next((n.attrs.get('value') for n in Tree(client.request(BASE+'/_layout/tokenhtml')).root.walk() if n.attrs.get('name')=='__RequestVerificationToken'),None)
        if not token:raise ValueError('The City’s search session could not be started. Open the official lookup page.')
        cookie='';matches={};more=False
        for page in range(1,4):
            params={'base64SecureConfiguration':layout['Base64SecureConfiguration'],'sortExpression':layout.get('SortExpression',''),
                'search':number,'page':page,'pageSize':10,'pagingCookie':cookie,'filter':None,'metaFilter':None,'timezoneOffset':0,'customParameters':[]}
            data=json.loads(client.request(endpoint,params,token))
            if not isinstance(data,dict) or not isinstance(data.get('Records'),list) or type(data.get('MoreRecords')) is not bool or data.get('PageNumber')!=page:raise ValueError('The City returned an incomplete or unexpected case search response.')
            for raw in data['Records']:
                item=parse_record(raw,number,details)
                if item:matches[item['url']]=item
            more=data['MoreRecords']
            if not more:break
            cookie=data.get('NextPagePagingCookie')
            if not data['Records'] or not cookie:raise ValueError('The City could not complete the case search.')
        if len(matches)==1 and not more:return {**base,'status':'found','record':next(iter(matches.values()))}
        if len(matches)>1 or more:return {**base,'status':'ambiguous','message':'The City returned multiple or incomplete matches. Open the official lookup to confirm the exact case.'}
        return {**base,'status':'not_found','message':'No exact public case-number match was returned. Check the full number or open the City lookup; this does not mean the issue is resolved.'}
    except Exception as error:
        if isinstance(error,urllib.error.HTTPError):message=f'The City 311 service returned HTTP {error.code}.'
        elif isinstance(error,(TimeoutError,socket.timeout)):message='The City 311 lookup timed out.'
        elif isinstance(error,urllib.error.URLError):message='Could not connect securely to the City 311 service. Check internet access or network restrictions.'
        elif isinstance(error,(json.JSONDecodeError,KeyError,TypeError,StopIteration)):message='The City 311 response format changed or the service is unavailable.'
        else:message=str(error)
        return {**base,'status':'unavailable','message':message+' No current status was retrieved. Use the official lookup link to retry.'}
