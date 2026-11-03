"""Strict selected-community identity and WGS84 containment. Display approximations never qualify."""
import math
import re
from communities import profile, matches_name

def normalized(value): return re.sub(r'\s+',' ',str(value or '')).strip().upper()

def validate_feature(feature):
    if not isinstance(feature,dict): raise ValueError('Boundary is not a feature')
    p=feature.get('properties') or {}
    names=[p[k] for k in ('SNBNAME','SN_NAME','SUPER_NEIGHBORHOOD','SuperNeighborhood') if k in p]
    numbers=[p[k] for k in ('POLYID','SN_NUMBER','SN_NUM','SNBNO') if k in p]
    if not names or not all(matches_name(v) for v in names): raise ValueError('Boundary name does not match '+profile()['officialName'])
    if not numbers or not all(str(v).strip() in {profile()['id'],profile()['id']+'.0'} for v in numbers): raise ValueError('Boundary number does not match '+profile()['id'])
    g=feature.get('geometry') or {}; typ=g.get('type'); coords=g.get('coordinates')
    if typ not in ('Polygon','MultiPolygon') or not coords: raise ValueError('Unsupported boundary geometry')
    polygons=[coords] if typ=='Polygon' else coords
    for polygon in polygons:
        if not polygon: raise ValueError('Empty polygon')
        for ring in polygon:
            if len(ring)<4 or ring[0][:2]!=ring[-1][:2]: raise ValueError('Boundary ring is not closed')
            for point in ring:
                if len(point)<2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in point[:2]): raise ValueError('Invalid boundary coordinates')
                if not (-96<point[0]<-94 and 28<point[1]<31): raise ValueError('Boundary is not Houston WGS84 longitude/latitude')
    return feature

def select_feature(collection):
    valid=[]
    if collection.get('error'): raise ValueError('Boundary service returned an error')
    if collection.get('exceededTransferLimit'): raise ValueError('Boundary response was truncated')
    for feature in collection.get('features',[]):
        try: valid.append(validate_feature(feature))
        except ValueError: pass
    if len(valid)!=1: raise ValueError('Expected exactly one official SN '+profile()['id']+' boundary feature')
    return valid[0]

def ring_relation(x,y,ring):
    inside=False
    for a,b in zip(ring,ring[1:]):
        ax,ay=a[:2];bx,by=b[:2]
        cross=(x-ax)*(by-ay)-(y-ay)*(bx-ax)
        if abs(cross)<1e-12 and min(ax,bx)-1e-12<=x<=max(ax,bx)+1e-12 and min(ay,by)-1e-12<=y<=max(ay,by)+1e-12: return 'edge'
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax: inside=not inside
    return 'inside' if inside else 'outside'

def contains(lng,lat,feature):
    validate_feature(feature)
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (lng,lat)): return False
    g=feature['geometry']; polys=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
    for poly in polys:
        if ring_relation(lng,lat,poly[0])=='inside' and all(ring_relation(lng,lat,r)=='outside' for r in poly[1:]): return True
    return False

def precise_address(candidate,requested,zip_code=None):
    attrs=candidate.get('attributes') or {}
    if float(candidate.get('score') or 0)<95: return False
    if attrs.get('Addr_type') not in {'PointAddress','Subaddress','StreetAddress'}: return False
    if zip_code:
        if str(attrs.get('Postal','')).split('-')[0]!=zip_code:return False
    elif normalized(attrs.get('City'))!='HOUSTON': return False
    asked=re.match(r'^\s*(\d+[A-Za-z]?)\s+(.+)',requested)
    if not asked or normalized(attrs.get('AddNum'))!=asked[1].upper(): return False
    if re.search(r'\b(?:TO|THROUGH)\b|&|\d\s*-\s*\d',requested,re.I): return False
    # Compare meaningful street tokens; suffix/direction abbreviations are normalized.
    synonyms={'STREET':'ST','AVENUE':'AVE','DRIVE':'DR','ROAD':'RD','BOULEVARD':'BLVD','LANE':'LN','COURT':'CT','NORTH':'N','SOUTH':'S','EAST':'E','WEST':'W'}
    def tokens(s): return [synonyms.get(w,w) for w in re.findall(r'[A-Z0-9]+',normalized(s))]
    req=tokens(asked[2].split(',')[0]); street=tokens(attrs.get('StName',''))
    if not street or not all(w in req for w in street):return False
    candidate_directions=tokens(' '.join(str(attrs.get(k,'') or '') for k in ('StPreDir','StDir')))
    requested_directions=[w for w in req if w in {'N','S','E','W','NE','NW','SE','SW'}]
    return sorted(candidate_directions)==sorted(requested_directions)
