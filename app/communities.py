"""Official community identities and request-local selection.

The original data directory always belongs to SN 55. A selection never moves,
renames, or re-labels that database. Workers retain the context they started in.
"""
import contextlib
import contextvars
import json
import re
from pathlib import Path
from paths import APP_DIR

CATALOG = json.loads((APP_DIR / 'communities.json').read_text(encoding='utf-8'))
PROFILES = {p['id']: p for p in CATALOG['communities']}
CURRENT = contextvars.ContextVar('ledger_community', default='55')

def profile(ident=None):
    key = CURRENT.get() if ident is None else str(ident)
    if key not in PROFILES:
        raise ValueError('Choose a Super Neighborhood from the list.')
    return PROFILES[key]

@contextlib.contextmanager
def selected(ident):
    token = CURRENT.set(profile(ident)['id'])
    try:
        yield profile()
    finally:
        CURRENT.reset(token)

def label():
    p = profile()
    return p['name'] + ' SN ' + p['id']

def keywords(ident=None):
    p = profile(ident)
    return p['aliases'] + ['Super Neighborhood ' + p['id'], 'SN ' + p['id']]

def matches_name(value):
    normalize = lambda x: re.sub(r'\s+', ' ', str(x).strip()).upper()
    # Only documented full names/aliases qualify. No substring neighborhood match.
    return normalize(value) in {normalize(x) for x in [profile()['officialName']]}

def data_root(root, ident=None):
    p = profile(ident)
    return Path(root) if p['id'] == '55' else Path(root) / 'communities' / p['id']

def remembered(root):
    try:
        return profile(json.loads((Path(root) / 'community-selection.json').read_text())['id'])['id']
    except (OSError, ValueError, KeyError, TypeError):
        return '55'

def remember(root, ident):
    ident = profile(ident)['id']
    path = Path(root) / 'community-selection.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'id': ident}), encoding='utf-8')
    temporary.replace(path)

