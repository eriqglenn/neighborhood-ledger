"""Anonymous read-only adapter for the City's public Current Agenda Spreadsheet.

Uses the grid configuration and anti-forgery handshake published in the page.
Does not sign in, change filters, or call the portal's AI endpoints.
"""
import base64
import datetime as dt
import hashlib
import http.cookiejar
import json
import re
from communities import profile, label, matches_name
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from plat_ingestion import IngestionError, POLICY

BASE='https://plattracker.powerappsportals.us'
PAGE=BASE+'/CurrentAgendaSpreadsheet/'
FIELDS={'neighborhood':'pt_superneighborhoodtext','case':'pt_name','title':'pt_fullsubname_reformatted','date':'ab.pt_cycleenddate','activity':'pt_applocation','special':'pt_specialrequest','url':'pt_subdivisionplatpdflink','developer':'pt_devorgname','applicant':'pt_applicantid','organization':'pt_organizationid','acreage':'pt_propertysize','lots':'pt_lotcount','landUse':'pt_landuse','appraisalId':'pt_countytaxid','majorThoroughfare':'pt_majorthroughfare'}

class PageParser(HTMLParser):
    def __init__(self): super().__init__();self.grid=None;self.token_url=None;self.token=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'entity-grid' in a.get('class','').split() and self.grid is None: self.grid=a
        if a.get('id')=='antiforgerytoken': self.token_url=a.get('data-url')
        if a.get('name')=='__RequestVerificationToken': self.token=a.get('value')

def same_host(path):
    url=urllib.parse.urljoin(BASE,path)
    if urllib.parse.urlsplit(url).netloc!=urllib.parse.urlsplit(BASE).netloc or not url.startswith('https://'): raise IngestionError('Public portal endpoint changed host')
    return url

class Transport:
    def __init__(self): self.op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def __call__(self,url,body=None,token=None):
        headers={'User-Agent':'NeighborhoodLedger/12.2','Accept':'application/json' if body is not None else 'text/html'}
        if body is not None: headers.update({'Content-Type':'application/json; charset=utf-8','X-Requested-With':'XMLHttpRequest','__RequestVerificationToken':token,'Referer':PAGE})
        request=urllib.request.Request(same_host(url),data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with self.op.open(request,timeout=25) as response:
            if urllib.parse.urlsplit(response.url).netloc!=urllib.parse.urlsplit(BASE).netloc or '/signin' in response.url.lower(): raise IngestionError('Public spreadsheet is no longer anonymously accessible')
            raw=response.read(12_000_001)
            if len(raw)>12_000_000: raise IngestionError('Public spreadsheet page exceeds size limit')
            return raw

def parse_record(raw,provenance,now):
    if raw.get('EntityName')!='pt_application' or not isinstance(raw.get('Attributes'),list): raise IngestionError('Unexpected public plat record schema')
    attrs={a['Name']:a.get('DisplayValue','') for a in raw['Attributes']}
    if len(attrs)!=len(raw['Attributes']): raise IngestionError('Duplicate public plat attributes')
    v={k:str(attrs.get(field,'') or '').strip() for k,field in FIELDS.items()}
    if not matches_name(v['neighborhood']): return None,'not_exact_selected_neighborhood'
    if not v['case'] or not v['title']: return None,'missing_identity'
    try: date=dt.datetime.fromisoformat(v['date'].replace('Z','+00:00')).date()
    except ValueError: return None,'invalid_pc_date'
    # A portal record is not a current agenda merely because it was downloaded today.
    if not now.date()-dt.timedelta(days=14)<=date<=now.date()+dt.timedelta(days=45): return None,'agenda_date_outside_current_window'
    url=v['url'] if re.match(r'^https://[^/]+',v['url']) else PAGE
    stamp=now.isoformat()
    return {'kind':'Plat','externalKey':'plat:'+v['case']+':'+date.isoformat(),'caseNo':v['case'],'title':v['title'],'date':date.isoformat(),'status':'Listed on public agenda; decision not established','activity':v['activity'],'special':v['special'],'sourceUrl':PAGE,'url':url,'source':'City of Houston · Public Current Agenda Spreadsheet','location':label(),'summary':f"{v['title']}. Planning Commission date: {date.isoformat()}. Exact {profile()['officialName']} field in the City's public agenda. A listing does not establish approval.",'matchMethod':'Exact City Super Neighborhood field match','mapStatus':'Needs a verified address or parcel location','sourceValues':v,'provenance':[{**provenance,'recordId':raw.get('Id'),'rawFields':attrs,'geographyPolicy':POLICY,'sourceMode':'public_current_agenda'}],'sourceMode':'public_current_agenda','retrievedAt':stamp,'currentAgendaStatus':'public_current_agenda',**{k:v[k] for k in ('developer','applicant','organization','acreage','lots','landUse','appraisalId','majorThoroughfare')}},None

def scan_public(root,transport=None,now=None):
    transport=transport or Transport();now=now or dt.datetime.now(dt.timezone.utc)
    folder=Path(root)/'plat_evidence';folder.mkdir(parents=True,exist_ok=True)
    page=transport(PAGE);parser=PageParser();parser.feed(page.decode('utf-8'))
    if not parser.grid or not parser.token_url: raise IngestionError('Public spreadsheet page schema changed')
    layouts=json.loads(base64.b64decode(parser.grid['data-view-layouts']))
    layout=next((x for x in layouts if x.get('Configuration',{}).get('Id')==parser.grid.get('data-selected-view')),None)
    if not layout or layout['Configuration'].get('EntityName')!='pt_application': raise IngestionError('Unexpected public spreadsheet configuration')
    if not set(FIELDS.values())<=set(c.get('LogicalName') for c in layout['Columns']): raise IngestionError('Public spreadsheet required columns changed')
    token_parser=PageParser();token_parser.feed(transport(same_host(parser.token_url)).decode('utf-8'))
    if not token_parser.token: raise IngestionError('Anonymous anti-forgery token unavailable')
    body={'base64SecureConfiguration':layout['Base64SecureConfiguration'],'sortExpression':layout.get('SortExpression'),'search':'','page':1,'pageSize':25,'pagingCookie':'','filter':None,'metaFilter':None,'timezoneOffset':300,'customParameters':[]}
    results=[];rejected=[];identities={};ids=set();total=None;pages=[]
    for number in range(1,31):
        body['page']=number
        raw=transport(same_host(parser.grid['data-get-url']),body,token_parser.token);data=json.loads(raw)
        if data.get('PageNumber')!=number or not isinstance(data.get('Records'),list) or type(data.get('MoreRecords')) is not bool: raise IngestionError('Public spreadsheet pagination schema changed')
        if total is None: total=data.get('ItemCount')
        if type(total) is not int or total<0 or total!=data.get('ItemCount'): raise IngestionError('Public agenda changed during pagination; retry the scan')
        digest=hashlib.sha256(raw).hexdigest();(folder/(digest+'.json')).write_bytes(raw);pages.append(digest)
        for row in data['Records']:
            if not row.get('Id') or row['Id'] in ids: raise IngestionError('Duplicate or missing record ID across public agenda pages')
            ids.add(row['Id'])
            record,reason=parse_record(row,{'sourceUrl':PAGE,'retrievedAt':now.isoformat(),'sha256':digest,'page':number},now)
            if reason: rejected.append({'recordId':row.get('Id'),'reason':reason});continue
            if record['externalKey'] in identities:
                prior=identities[record['externalKey']]
                if prior['sourceValues']!=record['sourceValues']: raise IngestionError('Conflicting public agenda case records')
                prior['provenance']+=record['provenance']
            else: results.append(record);identities[record['externalKey']]=record
        if not data['MoreRecords']: break
        if not data['Records']: raise IngestionError('Empty intermediate agenda page')
        body['pagingCookie']=data.get('NextPagePagingCookie','')
    else: raise IngestionError('Public agenda pagination limit reached; no partial success')
    if len(ids)!=total: raise IngestionError('Incomplete public agenda response')
    invalid=sum(x['reason']!='not_exact_selected_neighborhood' for x in rejected)
    result={'status':'partial' if invalid else 'success','sourceMode':'public_current_agenda','currentAgendaStatus':'public_current_agenda','sourceUrl':PAGE,'retrievedAt':now.isoformat(),'checkedAt':now.isoformat(),'totalRows':total,'results':results,'rejected':rejected,'pageHashes':pages,'coverage':'Complete public agenda pagination. Exact '+profile()['officialName']+' only. Agenda listing is not a decision.','warnings':[f'{invalid} {profile()["name"]} rows failed identity or date validation. Review the rejected-record evidence.'] if invalid else []}
    (folder/'public-latest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
