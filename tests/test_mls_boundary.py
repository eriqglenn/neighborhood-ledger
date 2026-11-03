import copy,unittest
from unittest.mock import patch
from test_mls import fixture
from mls_boundary import infer
import mls_service

def roads():
 return [
  {'name':'SAMPLE ST','paths':[[[-95.4201,29.8204],[-95.4195,29.8204]],[[-95.4195,29.8204],[-95.4189,29.8204]]]},
  {'name':'FIRST ST','paths':[[[-95.4201,29.8199],[-95.4201,29.8211]]]},
  {'name':'SECOND ST','paths':[[[-95.4189,29.8199],[-95.4189,29.8211]]]}]

class BoundaryDescriptions(unittest.TestCase):
 def test_two_sides_and_cross_streets(self):
  r=infer(fixture()['parcels'],roads(),{'street':'Sample Street'})
  self.assertEqual(r['fields'],{'blocks':'1500','street':'SAMPLE ST','sides':'north and south sides','blockfaces':'2','fromStreet':'FIRST ST','toStreet':'SECOND ST','description':'1500 block of SAMPLE ST, north and south sides, between FIRST ST and SECOND ST.'})
  self.assertEqual(r['notes'],[])
 def test_north_and_south_are_physical_sides_not_address_parity(self):
  for selected,expected in [(slice(4,None),'north side'),(slice(0,4),'south side')]:
   r=infer(fixture()['parcels'][selected],roads())
   self.assertEqual(r['fields']['sides'],expected);self.assertEqual(r['fields']['blockfaces'],'1')
 def test_reversed_digitization_keeps_the_same_description(self):
  network=roads()
  for r in network:r['paths']=[list(reversed(p)) for p in reversed(r['paths'])]
  self.assertEqual(infer(fixture()['parcels'],network)['fields'],infer(fixture()['parcels'],roads())['fields'])
 def test_north_south_street_has_east_west_sides(self):
  def rotate(p):return [-95.42-(p[1]-29.82),29.82+(p[0]+95.42)]
  parcels=fixture()['parcels'];network=roads()
  for p in parcels:p['geometry']['coordinates']=[[rotate(v) for v in ring] for ring in p['geometry']['coordinates']]
  for r in network:r['paths']=[[rotate(v) for v in path] for path in r['paths']]
  self.assertEqual(infer(parcels,network)['fields']['sides'],'east and west sides')
  self.assertEqual(infer(parcels[4:],network)['fields']['sides'],'west side')
 def test_opposite_side_t_junction_does_not_split_blockface(self):
  network=roads()+[{'name':'OTHER ST','paths':[[[-95.4195,29.8204],[-95.4195,29.8198]]]}]
  r=infer(fixture()['parcels'][4:],network)
  self.assertEqual(r['fields']['fromStreet'],'FIRST ST');self.assertEqual(r['fields']['toStreet'],'SECOND ST');self.assertFalse(r['notes'])
  both=infer(fixture()['parcels'],network)
  self.assertTrue(any('intervening' in n for n in both['notes']))
 def test_parallel_street_is_not_a_cross_street(self):
  network=roads()[:1]+[{'name':'PARALLEL ST','paths':[[[-95.4201,29.82041],[-95.4189,29.82041]]]}]
  r=infer(fixture()['parcels'],network)
  self.assertFalse(r['fields']['fromStreet']);self.assertFalse(r['fields']['toStreet']);self.assertFalse(r['fields']['description'])
 def test_missing_geometry_does_not_guess_sides_or_cross_streets(self):
  r=infer(fixture()['parcels'],[])
  self.assertEqual(r['fields']['blocks'],'1500');self.assertFalse(r['fields']['sides']);self.assertTrue(r['notes'])
 def test_corner_address_does_not_add_an_unrelated_block_number(self):
  parcels=fixture()['parcels'];parcels[0]['street']='9999 First Street'
  r=infer(parcels,roads());self.assertEqual(r['fields']['blocks'],'1500');self.assertTrue(any('other streets' in n for n in r['notes']))
 def test_truncated_road_context_is_not_used(self):
  with patch.object(mls_service,'gis',return_value={'exceededTransferLimit':True,'features':[]}):
   network,notes=mls_service.street_context(mls_service.polygon(fixture()['boundary']))
  self.assertEqual(network,[]);self.assertTrue(notes)
 def test_named_continuation_at_street_end(self):
  network=roads()[:2]+[{'name':'CONTINUATION DR','paths':[[[-95.4189,29.8204],[-95.418,29.8204]]]}]
  r=infer(fixture()['parcels'],network)
  self.assertEqual(r['fields']['toStreet'],'CONTINUATION DR')

if __name__=='__main__':unittest.main()
