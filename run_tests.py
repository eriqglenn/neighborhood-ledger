import os,sys,tempfile,unittest
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path[:0]=[str(root/'app'),str(root/'tests')]
with tempfile.TemporaryDirectory() as data:
 os.environ['NEIGHBORHOOD_LEDGER_DATA']=data
 suite=unittest.defaultTestLoader.discover(str(root/'tests'))
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 sys.exit(not result.wasSuccessful())
