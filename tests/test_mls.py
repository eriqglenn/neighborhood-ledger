import base64,copy,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import mls_service as m
from mls_documents import packet,form,map_pdf,submission
import pymupdf

def fixture():
 points=[[-95.42,29.82],[-95.419,29.82],[-95.419,29.821],[-95.42,29.821],[-95.42,29.82]]
 rows=[]
 for i,area in enumerate([6500,6000,6000,6000,5830,5500,3270,3000]):
  x=-95.42+(i%4)*.0002;y=29.82+(i//4)*.0005
  rows.append({'id':str(i),'account':f'{i:013d}','street':f'{1500+i*2} Sample Street','legalDescription':f'LT {i+1} BLK 1 SAMPLE SUBDIVISION','owner':'Sample Owner','area':area,'sourceArea':area,'use':'SFR','taxYear':'2026','selected':True,'confirmed':True,'lotsConfirmed':True,'lots':[],'geometry':{'type':'Polygon','coordinates':[[[x,y],[x+.00018,y],[x+.00018,y+.0003],[x,y+.0003],[x,y]]]}})
 return {'id':'a'*32,'title':'Sample Street MLS application','communityId':'55','revision':0,'step':4,'boundary':{'type':'Polygon','coordinates':[points]},'parcels':rows,'roads':[{'name':'SAMPLE ST','paths':[[[-95.4201,29.8204],[-95.4189,29.8204]]]},{'name':'FIRST ST','paths':[[[-95.4201,29.8199],[-95.4201,29.8211]]]},{'name':'SECOND ST','paths':[[[-95.4189,29.8199],[-95.4189,29.8211]]]}],'retrievedAt':'2026-11-01T12:00:00Z','details':{'description':'1500 block of Sample Street, north and south sides, between First Street and Second Street.','street':'Sample Street','fromStreet':'First Street','toStreet':'Second Street','sides':'north and south sides','blockfaces':'2','historic':'No','restrictions':'No','restrictionExplanation':'Applicant supplied recorded documents for staff review.','planner':'Sample Planner','meetingDate':'2026-11-01'},'applicant':{'name':'Sample Applicant','address':'1500 Sample Street, Houston, TX 77018','phone':'713-555-0100','email':'applicant@example.test'},'coapplicant':{},'attachments':[],'checks':{'completeBlockfaces':True,'contiguous':True,'unrestrictedLot':True}}

class MLSCases(unittest.TestCase):
 def test_planner_name_not_requested_or_exported(self):
  c=fixture();c['details'].pop('planner',None)
  self.assertEqual(m.analysis(c)['notes'],[])
  c['details']['planner']='Previously saved planner'
  with pymupdf.open(stream=form(c),filetype='pdf') as doc:
   fields={w.field_name:w.field_value for p in doc for w in (p.widgets() or [])}
   self.assertEqual(fields['preliminaryMeeting'],'2026-11-01')
   self.assertNotIn('Previously saved planner',''.join(p.get_text() for p in doc))
  c['details']['meetingDate']='';self.assertTrue(any('Record its date' in n for n in m.analysis(c)['notes']))
 def test_area_threshold_not_count(self):
  c=fixture();a=m.analysis(c);self.assertEqual(a['minimum'],5830);self.assertEqual(a['totalArea'],42100);self.assertFalse(a['issues']);c['details']['historic']='Yes';self.assertEqual(m.analysis(c)['minimum'],5830)
 def test_unknown_is_not_unrestricted(self):
  c=fixture();c['details']['restrictions']='Unknown';c['details']['historic']='Unknown';a=m.analysis(c);self.assertTrue(a['draft']);self.assertTrue(any('unknown' in n for n in a['notes']))
 def test_missing_and_multilot_validation(self):
  c=fixture();p=c['parcels'][0];p['lots']=[{'label':'Lot 1','area':1000,'use':'SFR'},{'label':'Lot 2','area':2000,'use':'SFR'}];self.assertTrue(any('add up' in s for s in m.analysis(c)['issues']))
 def test_loaded_properties_need_no_review_flags(self):
  c=fixture()
  for p in c['parcels']:p.update(confirmed=False,lotsConfirmed=False)
  a=m.analysis(c);self.assertFalse(a['issues']);self.assertEqual(a['minimum'],5830)
  self.assertTrue(all(not p['confirmed'] and not p['lotsConfirmed'] for p in c['parcels']))
 def test_excluded_lots_not_removed_from_boundary(self):
  c=fixture();c['parcels'][0]['use']='EXC';a=m.analysis(c);self.assertEqual(a['propertyCount'],8);self.assertEqual(a['singleFamilyPercent'],100);self.assertEqual(a['totalArea'],42100)
 def test_invalid_boundary(self):
  with self.assertRaises(ValueError):m.polygon({'type':'Polygon','coordinates':[[[0,0],[1,1],[1,0],[0,1],[0,0]]]})
 def test_incomplete_areas_do_not_produce_a_minimum(self):
  c=fixture();c['parcels'][0]['area']=None;a=m.analysis(c)
  self.assertIsNone(a['minimum']);self.assertEqual(a['table'],[]);self.assertTrue(a['issues'])
 def test_same_account_geometry_does_not_double_count_area(self):
  a,b=copy.deepcopy(fixture()['parcels'][:2]);b['account']=a['account'];b['area']=a['area'];b['legalDescription']=a['legalDescription']
  with patch.object(m,'gis',side_effect=[{'objectIds':[1,2]},{'features':[{},{}]}]),patch.object(m,'feature_row',side_effect=[a,b]):
   rows=m.features({});self.assertEqual(len(rows),1);self.assertEqual(rows[0]['area'],6500);self.assertGreater(m.shape(rows[0]['geometry']).area,m.shape(a['geometry']).area/2)
 def test_revision_and_community_isolation(self):
  with tempfile.TemporaryDirectory() as tmp:
   a=Path(tmp)/'55';b=Path(tmp)/'26';c=m.new_case(a,'55');self.assertEqual(m.list_cases(b),[]);c['title']='Saved';s=m.save_case(a,c,c['revision']);self.assertEqual(m.read_case(a,s['id'])['title'],'Saved')
   with self.assertRaises(ValueError):m.save_case(a,c,c['revision'])
   with self.assertRaises(ValueError):m.read_case(a,'../bad')
 def test_partial_results_rejected(self):
  with patch.object(m,'gis',side_effect=[{'objectIds':[1,2]},{'features':[]}]):
   with self.assertRaises(ValueError):m.features({})
 def test_packet_pages_and_blank_signatures(self):
  with tempfile.TemporaryDirectory() as tmp:
   raw=packet(fixture(),tmp);archive=zipfile.ZipFile(io.BytesIO(raw));self.assertEqual(len([n for n in archive.namelist() if n.endswith('.pdf')]),6)
   with pymupdf.open(stream=archive.read('01-Application-and-map.pdf'),filetype='pdf') as doc:
    self.assertEqual(len(doc),4);fields={w.field_name:w.field_value for p in doc for w in (p.widgets() or [])};self.assertEqual(fields['applicant_name'],'Sample Applicant');self.assertNotIn('signature',fields);self.assertNotIn('plannerAssigned',fields)
    self.assertIn('Application Information',doc[0].get_text());self.assertIn('Evidence of Support',doc[1].get_text());self.assertNotIn('Frequently Asked', ''.join(p.get_text() for p in doc))
    for i,p in enumerate(doc):self.assertIn(f'Page {i+1} of 4',p.get_text())
    self.assertFalse([w for w in doc[0].get_text('words') if w[0]>575 and 725<w[1]<747])
   with pymupdf.open(stream=archive.read('Reference/City-application-instructions.pdf'),filetype='pdf') as doc:self.assertEqual(len(doc),9)
   with pymupdf.open(stream=archive.read('Signs/Notification-sign-36x24.pdf'),filetype='pdf') as doc:self.assertEqual(doc[0].rect.width,2592);self.assertEqual(doc[0].rect.height,1728);self.assertIn('DRAFT',doc[0].get_text())
   Path('work/mls-demo-packet.zip').write_bytes(raw)
 def test_support_sheets_scale_with_selected_properties(self):
  for count in [1,4,5,9,13]:
   c=fixture();c['parcels']=[dict(c['parcels'][i%8],id=str(i)) for i in range(count)]
   with pymupdf.open(stream=form(c),filetype='pdf') as doc:
    self.assertEqual(len(doc),1+(count+3)//4)
    fields={w.field_name:w.field_value for p in doc for w in (p.widgets() or [])}
    self.assertEqual(sum(n.startswith('owner_') for n in fields),count)
 def test_map_labels_addresses_without_logo(self):
  c=fixture()
  from test_mls_boundary import roads
  c['roads']=roads()
  with pymupdf.open(stream=map_pdf(c),filetype='pdf') as doc:
   self.assertEqual(len(doc),1);self.assertEqual(tuple(doc[0].rect),(0,0,612,792));self.assertEqual(doc[0].get_images(),[])
   words={w[4] for w in doc[0].get_text('words')}
   for row in c['parcels']:self.assertIn(row['street'].split()[0],words)
   for name in ['SAMPLE ST','FIRST ST','SECOND ST']:self.assertIn(name,doc[0].get_text())
 def test_narrow_parcel_address_stays_inside(self):
  from mls_map import fit_address
  from shapely.geometry import box
  result=fit_address('12345',box(0,0,15,65),[])
  self.assertIsNotNone(result);self.assertTrue(box(0,0,15,65).covers(result[-1]))
 def test_attachment_metadata_server_owned(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=m.new_case(tmp,'55');c['attachments']=[{'id':'fake','ext':'../secret'}];c=m.save_case(tmp,c,c['revision']);self.assertEqual(c['attachments'],[])
   with self.assertRaises(ValueError):m.attach(tmp,c['id'],c['revision'],'bad.pdf','Plat',base64.b64encode(b'not a pdf').decode())

if __name__=='__main__':unittest.main()
