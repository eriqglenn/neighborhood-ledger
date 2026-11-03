"""Join current agenda cases to official City GIS outlines; never geocode plat names."""
import datetime as dt
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from geography import contains, normalized, validate_feature
from communities import profile

LAYER = 'https://mycity2.houstontx.gov/geoplat01/rest/services/PlatTracker/PT365_PLAT_MAPPING/MapServer/1'
POLICY = 'official-plat-outline-v1'


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        if response.url != url:
            raise ValueError('City GIS redirected; location verification stopped')
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError('City GIS response exceeds size limit')
        return raw


def geometry_feature(geometry):
    # Reuse the strict WGS84 geometry validator. Identity comes from the agenda join.
    feature = {'type': 'Feature', 'properties': {'SNBNAME': profile()['officialName'], 'POLYID': int(profile()['id'])}, 'geometry': geometry}
    validate_feature(feature)
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    if sum(len(r) for p in polygons for r in p) > 10000:
        raise ValueError('Plat outline is too complex to verify')
    for p in polygons:
        for r in p:
            if abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(r,r[1:]))) < 1e-12:
                raise ValueError('Plat outline has no area')
    return feature, polygons


def intersects(a, b, c, d):
    def cross(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    if max(a[0],b[0]) < min(c[0],d[0]) or max(c[0],d[0]) < min(a[0],b[0]) or max(a[1],b[1]) < min(c[1],d[1]) or max(c[1],d[1]) < min(a[1],b[1]): return False
    u,v,w,x=cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
    return (u*v <= 0 and w*x <= 0)


def verify_outline(geometry, boundary):
    validate_feature(boundary)
    feature, polygons = geometry_feature(geometry)
    bg=boundary['geometry']; bp=[bg['coordinates']] if bg['type']=='Polygon' else bg['coordinates']
    boundary_rings=[r for p in bp for r in p]
    for p in polygons:
        for ring in p:
            if not all(contains(x,y,boundary) for x,y,*_ in ring):
                raise ValueError('Plat outline touches or extends outside the selected official boundary')
            for a,b in zip(ring,ring[1:]):
                if any(intersects(a,b,c,d) for r in boundary_rings for c,d in zip(r,r[1:])):
                    raise ValueError('Plat outline crosses an official boundary or excluded hole')
    if any(contains(r[0][0],r[0][1],feature) for r in boundary_rings):
        raise ValueError('Plat outline encloses an excluded boundary area')
    # A display marker lies inside the actual outline, never at a guessed neighborhood center.
    for p in polygons:
        ys=sorted(set(v[1] for r in p for v in r))
        for low,high in zip(ys,ys[1:]):
            y=(low+high)/2; xs=[]
            for r in p:
                for a,b in zip(r,r[1:]):
                    if (a[1]>y)!=(b[1]>y): xs.append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
            xs.sort()
            for left,right in zip(xs,xs[1:]):
                x=(left+right)/2
                if contains(x,y,feature) and contains(x,y,boundary): return x,y
    raise ValueError('No interior display point could be verified')


def enrich(result, root, *, transport=fetch, boundary_loader=None, now=None):
    rows=result.get('results',[])
    if not rows or result.get('sourceMode')!='public_current_agenda': return result
    stamp=(now or dt.datetime.now(dt.timezone.utc)).isoformat()
    folder=Path(root)/'plat_evidence';folder.mkdir(parents=True,exist_ok=True)
    result['mapCoverage']={'mapped':0,'unmapped':len(rows),'checkedAt':stamp,'sourceUrl':LAYER}
    # Explicit nulls invalidate old map evidence when a refreshed source cannot verify it.
    for row in rows:
        row.update(lat=None,lng=None,mapGeometry=None,mapVerification=None,mapStatus='Official plat location not yet verified')
    try:
        if boundary_loader is None:
            from neighborops_server import get_boundary
            boundary_loader=get_boundary
        boundary=boundary_loader();validate_feature(boundary)
        cases=[r['caseNo'] for r in rows]
        if len(cases)>200 or any(not re.fullmatch(r'\d{4}-\d{4}',c) for c in cases): raise ValueError('Unexpected plat case-number format or count')
        query=LAYER+'/query?'+urllib.parse.urlencode({'where':'AppNo IN ('+','.join("'"+c+"'" for c in cases)+')','outFields':'*','returnGeometry':'true','outSR':'4326','f':'geojson'})
        raw=transport(query);data=json.loads(raw)
        folder=Path(root)/'plat_evidence';folder.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256(raw).hexdigest();(folder/(digest+'.geojson')).write_bytes(raw)
        if data.get('error') or data.get('exceededTransferLimit') or data.get('type')!='FeatureCollection' or not isinstance(data.get('features'),list): raise ValueError('Incomplete or invalid City GIS response')
        by_case={}
        for f in data['features']:
            case=f.get('properties',{}).get('AppNo')
            if case not in cases: raise ValueError('City GIS returned an unrequested case')
            by_case.setdefault(case,[]).append(f)
        for row in rows:
            try:
                matches=by_case.get(row['caseNo'],[])
                if len(matches)!=1: raise ValueError('No unique official outline for this exact case number')
                feature=matches[0];p=feature['properties']
                if not p.get('OBJECTID') or normalized(p.get('SubdivisionName'))!=normalized(row['title']): raise ValueError('Official case name or feature identity does not match the agenda')
                x,y=verify_outline(feature.get('geometry'),boundary)
                row.update(lat=y,lng=x,mapGeometry=feature['geometry'],mapStatus='Official City plat outline; exact case match and full selected-neighborhood containment verified',mapVerification={'policy':POLICY,'sourceUrl':query,'layerUrl':LAYER,'sha256':digest,'checkedAt':stamp,'caseNo':row['caseNo'],'objectId':p['OBJECTID'],'sourceFields':p,'boundarySource':boundary['properties'].get('ledgerSourceUrl'),'boundaryCheckedAt':boundary['properties'].get('ledgerCheckedAt'),'boundarySha256':hashlib.sha256(json.dumps(boundary,sort_keys=True).encode()).hexdigest(),'markerMeaning':'Display point inside official plat outline; not a street address'})
                result['mapCoverage']['mapped']+=1
            except (ValueError,KeyError,TypeError) as exc:
                row['mapStatus']='Not mapped: '+str(exc)
        result['mapCoverage']['unmapped']=len(rows)-result['mapCoverage']['mapped']
    except Exception as exc:
        result['mapCoverage']['error']=str(exc)
        for row in rows: row['mapStatus']='Location check unavailable: '+str(exc)
    if result['mapCoverage']['unmapped']:
        result.setdefault('warnings',[]).append(str(result['mapCoverage']['unmapped'])+' plat locations could not be verified; records remain available without map markers.')
    (Path(root)/'plat_evidence'/'locations-latest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
