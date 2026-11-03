import copy,unittest
from unittest.mock import patch
import pymupdf
import mls_service as m
from mls_map import map_pdf
from test_mls import fixture
from test_mls_boundary import roads

class StreetRecovery(unittest.TestCase):
 def test_export_recovers_missing_roads_without_mutating_saved_case(self):
  c=fixture();c['roads']=[];c['details']['street']='Sample';c['details']['fromStreet']='';c['details']['toStreet']='';before=copy.deepcopy(c)
  with patch.object(m,'street_context',return_value=(roads(),[])) as fetch:
   with pymupdf.open(stream=map_pdf(c),filetype='pdf') as doc:
    text=doc[0].get_text()
    for name in ['SAMPLE STREET','FIRST STREET','SECOND STREET']:self.assertIn(name,text)
   fetch.assert_called_once()
  self.assertEqual(c,before)
 def test_export_fails_clearly_if_streets_cannot_be_recovered(self):
  c=fixture();c['roads']=[]
  with patch.object(m,'street_context',return_value=([],['Unavailable'])):
   with self.assertRaisesRegex(ValueError,'Street names could not be loaded'):map_pdf(c)
 def test_unrelated_saved_streets_are_not_accepted(self):
  c=fixture();c['roads']=[{'name':'OTHER ST','paths':roads()[0]['paths']}]
  with patch.object(m,'street_context',return_value=(roads(),[])) as fetch:
   self.assertTrue(m.map_roads_ready(m.ensure_map_roads(c)));fetch.assert_called_once()
 def test_existing_street_geometry_still_works_offline(self):
  with patch.object(m,'street_context',side_effect=AssertionError('Unexpected request')):
   self.assertTrue(map_pdf(fixture()).startswith(b'%PDF'))
 def test_post_failure_retries_get_and_retains_street_type(self):
  response={'features':[{'attributes':{'NAME':'SAMPLE','TYPE':'ST'},'geometry':{'paths':roads()[0]['paths']}}]}
  with patch.object(m,'gis',side_effect=[ValueError('Temporary failure'),response]) as fetch:
   network,warnings=m.street_context(m.polygon(fixture()['boundary']))
  self.assertEqual(network[0]['name'],'SAMPLE ST');self.assertFalse(warnings)
  self.assertEqual(fetch.call_args.kwargs,{'method':'GET'})
 def test_failed_refresh_does_not_erase_working_roads(self):
  c=fixture()
  with patch.object(m,'street_context',return_value=([],['Unavailable'])):
   result=m.describe_boundary({'geometry':c['boundary'],'parcels':c['parcels'],'roads':roads(),'roadContextVersion':1,'refresh':True})
  self.assertEqual(result['roads'],roads());self.assertEqual(result['fields']['street'],'SAMPLE ST')
