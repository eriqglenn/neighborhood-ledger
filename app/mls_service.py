"""Applicant-side SMLS projects. Public GIS lookups never imply City approval."""
import base64, copy, datetime as dt, hashlib, json, math, re, threading, uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from shapely.geometry import Polygon, shape, mapping
from shapely.ops import unary_union
import deed_search

LOCK=threading.RLock()
PARCEL=deed_search.PARCEL
ROADS='https://www.gis.hctx.net/arcgis/rest/services/ITC/CTS_roads/MapServer/0'
FIELDS=deed_search.FIELDS+',OBJECTID,owner_name_1,owner_name_2,confidential_flag,land_sqft,state_class,land_use'
USES={'SFR','MF','COM','VAC','EXC','UNKNOWN'}
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def clean(value,limit=2000):return re.sub(r'\s+',' ',str(value or '')).strip()[:limit]
def identifier(value):
 if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value):raise ValueError('Choose a saved MLS application.')
 return value
def project_dir(root):
 p=Path(root)/'mls-applications';p.mkdir(parents=True,exist_ok=True);return p
def read_case(root,ident):
 p=project_dir(root)/(identifier(ident)+'.json')
 if not p.exists():raise ValueError('Application not found in this neighborhood.')
 return json.loads(p.read_text(encoding='utf-8'))
def list_cases(root):
 items=[]
 for p in project_dir(root).glob('*.json'):
  c=json.loads(p.read_text(encoding='utf-8'));items.append({k:c.get(k) for k in ['id','title','updated','step','revision']})
 return sorted(items,key=lambda c:c['updated'],reverse=True)
def new_case(root,community):
 c={'id':uuid.uuid4().hex,'title':'New MLS application','communityId':community,'revision':0,'step':0,'created':stamp(),'updated':stamp(),'address':{},'boundary':None,'parcels':[],'roads':[],'details':{'restrictions':'Unknown','historic':'Unknown','blockfaces':'1'},'applicant':{},'coapplicant':{},'attachments':[],'checks':{}}
 return save_case(root,c,-1)
def save_case(root,c,revision):
 ident=identifier(c.get('id'));p=project_dir(root)/(ident+'.json')
 if len(json.dumps(c))>10_000_000:raise ValueError('Application is too large to save.')
 with LOCK:
  old=read_case(root,ident) if p.exists() else None
  if (old['revision'] if old else -1)!=revision:raise ValueError('This application changed in another window. Reload it before saving again.')
  if old and c.get('communityId')!=old.get('communityId'):raise ValueError('An application cannot change neighborhoods.')
  c=copy.deepcopy(c);c['revision']=revision+1;c['updated']=stamp();c['title']=clean(c.get('title'),140) or 'MLS application'
  # Attachment metadata is server-owned, never accepted from a browser save.
  c['attachments']=old.get('attachments',[]) if old else []
  temp=p.with_suffix('.tmp');temp.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8');temp.replace(p)
 return c
def attach(root,ident,revision,name,kind,encoded):
 if kind not in {'Plat','Deed restrictions','Signed support','Staff letter','Posting photo','Other'}:raise ValueError('Choose the document type.')
 try:raw=base64.b64decode(encoded,validate=True)
 except Exception:raise ValueError('File could not be read.') from None
 if not 0<len(raw)<=8_000_000:raise ValueError('Choose a PDF or image smaller than 8 MB.')
 import pymupdf
 if raw.startswith(b'%PDF'):
  with pymupdf.open(stream=raw,filetype='pdf') as pdf:
   if pdf.is_encrypted or not 1<=len(pdf)<=300:raise ValueError('Use an unlocked PDF with 1–300 pages.')
  ext='.pdf'
 elif raw.startswith(b'\x89PNG\r\n\x1a\n'):ext='.png'
 elif raw.startswith(b'\xff\xd8\xff'):ext='.jpg'
 else:raise ValueError('Choose a PDF, PNG or JPEG file.')
 with LOCK:
  c=read_case(root,ident)
  if c['revision']!=revision:raise ValueError('Save your changes before adding a file.')
  if len(c['attachments'])>=40:raise ValueError('This application already has 40 attachments.')
  file_id=uuid.uuid4().hex;folder=project_dir(root)/ident;folder.mkdir(exist_ok=True)
  (folder/(file_id+ext)).write_bytes(raw)
  c['attachments'].append({'id':file_id,'name':clean(Path(name).name,180),'kind':kind,'ext':ext,'added':stamp(),'sha256':hashlib.sha256(raw).hexdigest()})
  c['revision']+=1;c['updated']=stamp();p=project_dir(root)/(ident+'.json');temp=p.with_suffix('.tmp');temp.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8');temp.replace(p)
 return c

def gis(service,params,method='POST'):
 data={'f':'json',**params};url=service+'/query'
 try:
  encoded=urlencode(data)
  with urlopen(Request(url+'?'+encoded if method=='GET' else url,data=encoded.encode() if method!='GET' else None,headers={'User-Agent':'NeighborhoodLedgerMLSNoAI/1.0'}),timeout=20 if service==ROADS else 35) as response:raw=response.read(12_000_001)
  if len(raw)>12_000_000:raise ValueError('The map response was too large. Draw a smaller area.')
  result=json.loads(raw)
 except (OSError,json.JSONDecodeError) as e:raise ValueError('The County map service could not be reached. Check your connection and try again. Saved properties have not been replaced.') from e
 if not isinstance(result,dict) or result.get('error'):raise ValueError('The County map service could not complete this lookup. Try again later.')
 return result
def geojson(geometry):
 # ArcGIS polygon rings may contain holes or multiple disjoint parts.
 rings=geometry.get('rings',[]);polys=[Polygon(r) for r in rings if len(r)>=4]
 if not polys:raise ValueError('Parcel has no usable boundary.')
 result=polys[0]
 for p in polys[1:]:result=result.symmetric_difference(p)
 if not result.is_valid:result=result.buffer(0)
 return mapping(result)
def polygon(value):
 try:g=shape(value)
 except Exception:raise ValueError('Draw a boundary on the map first.') from None
 if g.geom_type!='Polygon' or not g.is_valid or g.is_empty or len(g.exterior.coords)>200:raise ValueError('Draw one simple boundary without crossing its lines.')
 x1,y1,x2,y2=g.bounds
 if not all(math.isfinite(n) for n in g.bounds) or not (-96<x1<x2<-94 and 29<y1<y2<31):raise ValueError('Choose a boundary in the Houston area.')
 if x2-x1>.025 or y2-y1>.025:raise ValueError('This application covers one blockface or two opposing blockfaces. Draw a smaller area.')
 return g
def feature_row(f):
 a=f['attributes'];r=deed_search.property_record(a);r['geometry']=geojson(f['geometry']);r['id']=str(a['OBJECTID'])
 r['owner']='' if clean(a.get('confidential_flag')).upper() in {'Y','YES','1','TRUE'} else ' / '.join(clean(a.get(k)) for k in ['owner_name_1','owner_name_2'] if clean(a.get(k)))
 area=a.get('land_sqft');r['area']=float(area) if isinstance(area,(int,float)) and math.isfinite(area) and area>0 else None
 r['sourceClass']=clean(a.get('state_class'));r['sourceUse']=clean(a.get('land_use'))
 # County codes are evidence; the applicant confirms the use instead of an inferred eligibility claim.
 code=r['sourceUse'];state=r['sourceClass']
 r['use']='SFR' if state=='A1' and code in {'1001','1003','2001','2003'} else 'VAC' if code in {'1000','1002','2000','2002','4200','4300','4400'} else 'MF' if code in {'4209','4211','4212','4214','4221','4222'} else 'EXC' if code in {'4611','4612','4613','4620','4930'} else 'COM' if state=='F1' and code not in {'4300','4500','4542','4543'} else 'UNKNOWN'
 r['useSuggested']=r['use']!='UNKNOWN';r['confirmed']=False;r['lotsConfirmed']=False;r['lots']=[];r['selected']=True;r['sourceArea']=r['area']
 return r
def features(params):
 ids=gis(PARCEL,{**params,'returnIdsOnly':'true'}).get('objectIds')
 if ids is None:raise ValueError('The County returned an incomplete property list. Retry the search.')
 if len(ids)>350:raise ValueError('The boundary contains too many properties for a block application. Draw a smaller area.')
 result=[]
 for i in range(0,len(ids),75):
  data=gis(PARCEL,{'objectIds':','.join(str(int(n)) for n in ids[i:i+75]),'outFields':FIELDS,'returnGeometry':'true','outSR':4326})
  if data.get('exceededTransferLimit') or len(data.get('features',[]))!=len(ids[i:i+75]):raise ValueError('The County returned an incomplete property list. Retry before continuing.')
  result.extend(feature_row(f) for f in data['features'])
 merged={}
 for r in result:
  key=r['account']
  if key not in merged:merged[key]=r;continue
  prior=merged[key]
  prior['geometry']=mapping(unary_union([shape(prior['geometry']),shape(r['geometry'])]))
  if prior['area']!=r['area'] or prior['legalDescription']!=r['legalDescription']:
   prior['area']=None;prior['sourceConflict']=True
 return list(merged.values())
def locate(number,street,zip_code):
 result=deed_search.find_properties_fields(number,street,zip_code)
 if not result['candidates']:return {'candidates':[],'retrievedAt':stamp()}
 return result
def neighborhood(account):
 if not re.fullmatch(r'\d{13}',str(account)):raise ValueError('Choose a matching address.')
 matches=features({'where':"HCAD_NUM = '"+account+"'"})
 if not matches:raise ValueError('No parcel boundary was returned for this address.')
 g=unary_union([shape(r['geometry']) for r in matches]);x,y=g.centroid.coords[0];b=g.buffer(.0018).bounds
 nearby=features({'geometry':','.join(map(str,b)),'geometryType':'esriGeometryEnvelope','inSR':4326,'spatialRel':'esriSpatialRelIntersects'})
 return {'center':[y,x],'parcels':nearby,'retrievedAt':stamp()}
def scan_boundary(value):
 g=polygon(value);query={'geometry':json.dumps({'rings':[list(g.exterior.coords)],'spatialReference':{'wkid':4326}}),'geometryType':'esriGeometryPolygon','inSR':4326,'spatialRel':'esriSpatialRelIntersects'}
 rows=features(query)
 for r in rows:
  p=shape(r['geometry']);fraction=g.intersection(p).area/p.area if p.area else 0
  r['coverage']=round(fraction,4);r['selected']=fraction>=.5;r['edge']=fraction<.98
 roads,warnings=street_context(g)
 return {'parcels':rows,'roads':roads,'roadContextVersion':1,'warnings':warnings,'retrievedAt':stamp(),'source':PARCEL}

def street_context(g):
 # Retry the same authoritative service via GET when a transient failure or
 # a proxy blocks POST. An empty result is not a successful street lookup.
 query={'geometry':json.dumps({'rings':[list(g.buffer(.004).envelope.exterior.coords)],'spatialReference':{'wkid':4326}}),'geometryType':'esriGeometryPolygon','inSR':4326,'spatialRel':'esriSpatialRelIntersects'}
 for method in ['POST','GET']:
  try:
   params={**query,'outFields':'NAME,STREET,TYPE','outSR':4326,'returnGeometry':'true'}
   data=gis(ROADS,params) if method=='POST' else gis(ROADS,params,method='GET')
   if data.get('exceededTransferLimit'):raise ValueError('Street results were incomplete.')
   roads=[]
   for f in data.get('features',[]):
    a=f.get('attributes',{});name=clean(a.get('STREET') or ' '.join(str(a.get(k) or '') for k in ['NAME','TYPE']))
    paths=[p for p in f.get('geometry',{}).get('paths',[]) if len(p)>1]
    if name and paths:roads.append({'name':name,'paths':paths})
   if roads:return roads,[]
  except ValueError:pass
 return [],['Street lookup could not be completed. Retry Use map details. The application map needs street names before it can be downloaded.']

def map_roads_ready(case):
 from collections import Counter
 from mls_boundary import address_parts,street_key
 from shapely.geometry import LineString
 selected=[p for p in case.get('parcels',[]) if p.get('selected')]
 if not selected:return False
 counts=Counter(address_parts(p.get('street'))[1] for p in selected);counts.pop('',None)
 if not counts:return False
 name=counts.most_common(1)[0][0];area=unary_union([shape(p['geometry']) for p in selected]).buffer(.002)
 return any(street_key(r.get('name'))==name and any(len(path)>1 and LineString([v[:2] for v in path]).intersects(area) for path in r.get('paths',[])) for r in case.get('roads',[]))

def ensure_map_roads(case):
 """Recover missing geometry on export without changing saved applicant facts."""
 if map_roads_ready(case):return case
 c=copy.deepcopy(case);selected=[p for p in c.get('parcels',[]) if p.get('selected')]
 if not selected:raise ValueError('Select properties before downloading the application map.')
 c['roads'],_=street_context(unary_union([shape(p['geometry']) for p in selected]));c['roadContextVersion']=1
 if not map_roads_ready(c):raise ValueError('Street names could not be loaded for this map. Check your connection and try downloading again, or choose Use map details in Block details. Your selected lots and saved work are unchanged.')
 return c

def describe_boundary(body):
 from mls_boundary import infer
 g=polygon(body.get('geometry'));parcels=body.get('parcels',[])
 if not isinstance(parcels,list) or len(parcels)>350:raise ValueError('Choose properties within one block application.')
 roads=body.get('roads',[]);warnings=[]
 if body.get('refresh') or body.get('roadContextVersion')!=1 or not map_roads_ready({'parcels':parcels,'roads':roads}):
  fetched,warnings=street_context(g)
  if fetched:roads=fetched
 result=infer(parcels,roads,body.get('address'))
 return {**result,'roads':roads,'roadContextVersion':1,'notes':list(dict.fromkeys(warnings+result['notes']))}

def legal_lots(p):
 if p.get('lots'):
  lots=p['lots']
  if not isinstance(lots,list) or len(lots)>50:raise ValueError('Use at most 50 legal lots per account.')
  return [{**l,'address':p.get('street'),'account':p['account']} for l in lots]
 return [{'label':p.get('legalDescription',''),'area':p.get('area'),'use':p.get('use','UNKNOWN'),'address':p.get('street'),'account':p['account']}]
def analysis(c):
 rows=[p for p in c.get('parcels',[]) if p.get('selected')];issues=[];notes=[];lots=[];areas_complete=True
 d=c.get('details',{});checks=c.get('checks',{})
 if not rows:issues.append('Choose the properties in your application boundary.')
 if len(rows)>150:issues.append('A block application should cover one blockface or two opposing blockfaces. Check the selected properties.')
 if not checks.get('completeBlockfaces'):issues.append('Confirm that every lot on the selected blockface or opposing blockfaces is included.')
 if not checks.get('contiguous'):issues.append('Confirm that the selected area is contiguous.')
 for p in rows:
  address=p.get('street') or p.get('account')
  pl=legal_lots(p)
  for l in pl:
   if p.get('lots') and not clean(l.get('label')):issues.append(f'Enter a name for each legal lot at {address}.')
   try:area=float(l.get('area') or 0)
   except (ValueError,TypeError):area=0
   if not math.isfinite(area) or area<=0:issues.append(f'Enter the lot size for {address}.');areas_complete=False;continue
   use=l.get('use','UNKNOWN')
   if use not in USES or use=='UNKNOWN':issues.append(f'Choose the land use for {address}.')
   lots.append({**l,'area':area,'use':use})
  if p.get('lots') and p.get('area') and abs(sum(float(l.get('area') or 0) for l in pl)-float(p['area']))>max(1,float(p['area'])*.001):issues.append(f'Legal lot sizes for {address} do not add up to the property area.');areas_complete=False
 if d.get('blockfaces') not in {'1','2'}:issues.append('Choose one blockface or two opposing blockfaces.')
 if not d.get('street') or not d.get('fromStreet') or not d.get('toStreet') or not d.get('sides'):issues.append('Complete the street and cross-street description.')
 if not d.get('description') or '[' in d.get('description',''):issues.append('Confirm the written boundary description.')
 if not c.get('boundary'):issues.append('Draw the application boundary.')
 else:
  try:polygon(c['boundary'])
  except ValueError as e:issues.append(str(e))
 if d.get('restrictions') not in {'Yes','No','Unknown'}:issues.append('Answer the deed restriction question.')
 if d.get('restrictions')=='No' and not d.get('restrictionExplanation'):issues.append('Explain the evidence for your deed restriction answer.')
 if d.get('restrictions')=='Yes' and not any(a['kind']=='Deed restrictions' for a in c.get('attachments',[])):issues.append('Attach the deed restrictions referenced in your answer.')
 if d.get('restrictions')=='Unknown':notes.append('Deed restrictions are unknown; discuss this with Planning staff at the preliminary meeting.')
 if not checks.get('unrestrictedLot'):notes.append('Planning staff must confirm that at least one lot has no deed-restricted minimum lot size.')
 if not d.get('meetingDate'):notes.append('The application requires a preliminary meeting. Record its date before submission.')
 if not c.get('applicant',{}).get('name') or not c.get('applicant',{}).get('address'):issues.append('Enter the main applicant’s name and address.')
 if not c.get('applicant',{}).get('phone') or not c.get('applicant',{}).get('email'):issues.append('Enter the main applicant’s phone and email.')
 eligible=[l for l in lots if l['use']!='EXC'];sf=sum(l['use']=='SFR' for l in eligible);ratio=sf/len(eligible) if eligible else 0
 if rows and not eligible:notes.append('No qualifying residential lots are recorded. Ask Planning staff about eligibility.')
 if eligible and ratio<.6:notes.append('Recorded single-family use is below 60% of non-excluded lots. Ask Planning staff about eligibility.')
 total=sum(l['area'] for l in lots);threshold=.6 if d.get('historic')=='Yes' else .7
 if d.get('historic')=='Unknown':notes.append('Historic district status is unknown. The calculation below uses 70%; staff must confirm the applicable threshold.')
 running=0;minimum=None;table=[]
 for l in sorted(lots,key=lambda l:-l['area']):
  running+=l['area'];table.append({**l,'percent':l['area']/total*100 if total else 0,'cumulative':running/total*100 if total else 0})
  if minimum is None and total and running>=total*threshold-1e-7:minimum=l['area']
 if not areas_complete:minimum=None;table=[];notes.append('The minimum lot size calculation is unavailable until every lot area is complete and consistent.')
 return {'issues':list(dict.fromkeys(issues)),'notes':notes,'propertyCount':len(rows),'lotCount':len(lots),'singleFamilyPercent':round(ratio*100,1),'minimum':minimum,'threshold':int(threshold*100),'totalArea':total,'table':table,'signCount':2*int(d.get('blockfaces') or 1) if d.get('blockfaces') in {'1','2'} else 2,'draft':bool(issues or notes)}

def handle_get(handler,path,query):
 root=handler.server.store.root
 if path=='/api/mls/cases':return handler.send_json({'items':list_cases(root)})
 if path=='/api/mls/case':return handler.send_json(read_case(root,query.get('id',[''])[0]))
 if path=='/api/mls/template':return handler.serve_file(Path(__file__).parent/'mls-assets/application.pdf')
 if path in {'/api/mls/submission','/api/mls/map','/api/mls/sign'}:
  from mls_documents import submission,map_pdf,signs
  render,name={'/api/mls/submission':(submission,'MLS-Application-and-Map.pdf'),'/api/mls/map':(map_pdf,'MLS-Boundary-Map.pdf'),'/api/mls/sign':(signs,'MLS-Notification-Sign-36x24.pdf')}[path]
  c=read_case(root,query.get('id',[''])[0])
  if path!='/api/mls/sign':c=ensure_map_roads(c)
  return binary(handler,render(c),'application/pdf',name)
 if path=='/api/mls/file':
  c=read_case(root,query.get('id',[''])[0]);file_id=query.get('file',[''])[0]
  a=next((a for a in c['attachments'] if a['id']==file_id),None)
  if not a:raise ValueError('Attachment not found.')
  raw=(project_dir(root)/c['id']/(a['id']+a['ext'])).read_bytes();return binary(handler,raw,'application/octet-stream','attachment'+a['ext'])
 if path=='/api/mls/export':
  from mls_documents import packet
  c=ensure_map_roads(read_case(root,query.get('id',[''])[0]));raw=packet(c,root)
  return binary(handler,raw,'application/zip','MLS-Application-Packet.zip')
 raise ValueError('MLS endpoint not found.')
def binary(h,raw,mime,name):
 h.send_response(200);h.send_header('Content-Type',mime);h.send_header('Content-Length',str(len(raw)));h.send_header('Content-Disposition','attachment; filename="'+name+'"');h.send_header('Cache-Control','no-store');h.send_header('X-Content-Type-Options','nosniff');h.end_headers();h.wfile.write(raw)
def handle_post(handler,path,body):
 root=handler.server.store.root
 if path=='/api/mls/new':
  import communities
  return new_case(root,communities.profile()['id'])
 if path=='/api/mls/save':return save_case(root,body['case'],int(body['revision']))
 if path=='/api/mls/locate':return locate(body.get('number'),body.get('street'),body.get('zip'))
 if path=='/api/mls/neighborhood':return neighborhood(body.get('account'))
 if path=='/api/mls/boundary':return scan_boundary(body.get('geometry'))
 if path=='/api/mls/describe':return describe_boundary(body)
 if path=='/api/mls/check':return analysis(read_case(root,body['id']))
 if path=='/api/mls/attach':return attach(root,body['id'],int(body['revision']),body['name'],body['kind'],body['data'])
 if path=='/api/mls/plats':
  from mls_plats import PlatSearchClient
  name=clean(body.get('name'),100)
  if len(name)<3:raise ValueError('Enter the subdivision name.')
  return {**PlatSearchClient().search(name=name),'retrievedAt':stamp()}
 raise ValueError('MLS endpoint not found.')
