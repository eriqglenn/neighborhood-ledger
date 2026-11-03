import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from plat_locations import enrich,verify_outline,POLICY
from monitor import Monitor
from storage import Store

def polygon(points):return {'type':'Polygon','coordinates':[points]}
def box(x1,y1,x2,y2):return [[x1,y1],[x2,y1],[x2,y2],[x1,y2],[x1,y1]]
BOUNDARY={'type':'Feature','properties':{'SNBNAME':'GREATER FIFTH WARD','POLYID':55},'geometry':polygon(box(-95.4,29.7,-95.3,29.8))}
GEOM=polygon(box(-95.38,29.72,-95.36,29.74))
def row():return {'kind':'Plat','caseNo':'2026-1234','title':'Test Plat','lat':29.9,'lng':-95.9,'mapVerification':{'policy':'old'}}
def feature():return {'type':'Feature','properties':{'AppNo':'2026-1234','SubdivisionName':'Test Plat','OBJECTID':1},'geometry':copy.deepcopy(GEOM)}
class Locations(unittest.TestCase):
 def run_scan(self,features=None,**extra):
  data={'type':'FeatureCollection','features':[feature()] if features is None else features,**extra}
  with tempfile.TemporaryDirectory() as root:
   result=enrich({'sourceMode':'public_current_agenda','results':[row()]},Path(root),transport=lambda u:json.dumps(data).encode(),boundary_loader=lambda:copy.deepcopy(BOUNDARY))
   return result
 def test_exact_case_and_outline_provenance(self):
  r=self.run_scan();d=r['results'][0];self.assertEqual(r['mapCoverage']['mapped'],1);self.assertEqual(d['mapGeometry'],GEOM);self.assertEqual(d['mapVerification']['policy'],POLICY);self.assertEqual(len(d['mapVerification']['sha256']),64)
 def test_missing_outline_clears_prior_location(self):
  d=self.run_scan([])['results'][0];self.assertIsNone(d['lat']);self.assertIsNone(d['mapVerification'])
 def test_duplicate_case_is_not_arbitrarily_selected(self):self.assertEqual(self.run_scan([feature(),feature()])['mapCoverage']['mapped'],0)
 def test_name_mismatch(self):
  f=feature();f['properties']['SubdivisionName']='Other';self.assertEqual(self.run_scan([f])['mapCoverage']['mapped'],0)
 def test_wrong_case(self):
  f=feature();f['properties']['AppNo']='2026-9999';self.assertEqual(self.run_scan([f])['mapCoverage']['mapped'],0)
 def test_truncated_response(self):self.assertEqual(self.run_scan(exceededTransferLimit=True)['mapCoverage']['mapped'],0)
 def test_service_error_preserves_agenda(self):self.assertEqual(len(self.run_scan(error={'message':'unavailable'})['results']),1)
 def test_boundary_unavailable_does_not_erase_agenda(self):
  with tempfile.TemporaryDirectory() as root:
   r=enrich({'sourceMode':'public_current_agenda','results':[row()]},Path(root),boundary_loader=lambda:(_ for _ in ()).throw(ValueError('offline')));self.assertIsNone(r['results'][0]['lat']);self.assertEqual(r['mapCoverage']['mapped'],0)
 def test_outside_outline(self):
  with self.assertRaises(ValueError):verify_outline(polygon(box(-95.5,29.72,-95.36,29.74)),BOUNDARY)
 def test_touching_edge_rejected(self):
  with self.assertRaises(ValueError):verify_outline(polygon(box(-95.4,29.72,-95.36,29.74)),BOUNDARY)
 def test_enclosed_boundary_hole_rejected(self):
  b=copy.deepcopy(BOUNDARY);b['geometry']['coordinates'].append(box(-95.375,29.725,-95.37,29.73))
  with self.assertRaises(ValueError):verify_outline(GEOM,b)
 def test_crossing_concave_boundary_even_with_inside_vertices(self):
  b=copy.deepcopy(BOUNDARY);b['geometry']=polygon([[-95.4,29.7],[-95.3,29.7],[-95.3,29.8],[-95.34,29.8],[-95.34,29.74],[-95.36,29.74],[-95.36,29.8],[-95.4,29.8],[-95.4,29.7]])
  with self.assertRaises(ValueError):verify_outline(polygon(box(-95.38,29.75,-95.32,29.77)),b)
 def test_multipart_and_hole_marker(self):
  g={'type':'MultiPolygon','coordinates':[copy.deepcopy(GEOM['coordinates']),[box(-95.34,29.76,-95.32,29.78)]]};x,y=verify_outline(g,BOUNDARY);self.assertTrue(-95.4<x<-95.3 and 29.7<y<29.8)
 def test_unclosed_geometry_rejected(self):
  g=copy.deepcopy(GEOM);g['coordinates'][0].pop()
  with self.assertRaises(ValueError):verify_outline(g,BOUNDARY)
 def test_archive_not_mapped(self):
  r={'sourceMode':'archive','results':[row()]};self.assertIs(enrich(r,Path('.'),transport=lambda u:self.fail('archive lookup')),r)
 def test_development_scan_checks_both_without_news(self):
  with tempfile.TemporaryDirectory() as root,patch('monitor.fetch_feed',side_effect=AssertionError('news must not run')):
   calls=[];m=Monitor(Store(root),lambda:calls.append('plats') or {'results':[]},lambda:calls.append('permits') or {'results':[]});m.run('development');self.assertEqual(calls,['plats','permits'])
