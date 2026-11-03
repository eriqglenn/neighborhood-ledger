import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('NEIGHBORHOOD_LEDGER_DATA', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'NeighborhoodLedgerMLSNoAI' / 'Data')))
VERSION = '13.8 MLS (No AI)'

def data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

