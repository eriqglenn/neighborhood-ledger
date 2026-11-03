"""Describe selected blockfaces from parcel addresses and connecting street geometry."""
import math
import re
from collections import Counter
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, unary_union, nearest_points

VERSION = 1
SUFFIXES = {'STREET':'ST','DRIVE':'DR','ROAD':'RD','LANE':'LN','COURT':'CT',
 'BOULEVARD':'BLVD','AVENUE':'AVE','PLACE':'PL','CIRCLE':'CIR','PARKWAY':'PKWY',
 'TRAIL':'TRL','TERRACE':'TER','HIGHWAY':'HWY','NORTH':'N','SOUTH':'S','EAST':'E','WEST':'W'}

def street_key(value):
    words=re.sub(r'[^A-Z0-9 ]',' ',str(value or '').upper()).split()
    return ' '.join(SUFFIXES.get(w,w) for w in words)

def address_parts(value):
    match=re.match(r'^\s*(\d+)[A-Za-z]?\s+(.+?)(?:,|\s+#|\s+APT\s|\s+UNIT\s|$)',str(value or ''),re.I)
    return (int(match[1]),street_key(match[2])) if match else (None,'')

def points(geometry):
    if geometry.geom_type=='Point':return [geometry]
    if hasattr(geometry,'geoms'):return [p for g in geometry.geoms for p in points(g)]
    return []

def description(fields):
    if not all(fields.get(k) for k in ['blocks','street','sides','fromStreet','toStreet']):return ''
    noun='blocks' if '–' in fields['blocks'] else 'block'
    return f"{fields['blocks']} {noun} of {fields['street']}, {fields['sides']}, between {fields['fromStreet']} and {fields['toStreet']}."

def infer(parcels,roads,address=None):
    selected=[p for p in parcels if p.get('selected')]
    fields=dict.fromkeys(['blocks','street','sides','blockfaces','fromStreet','toStreet','description'],'')
    result={'version':VERSION,'fields':fields,'notes':[]}
    notes=result['notes']
    if not selected:
        notes.append('Select properties to fill the block description.');return result
    counts=Counter(address_parts(p.get('street'))[1] for p in selected)
    counts.pop('',None)
    if not counts:
        notes.append('Property addresses were unavailable. Enter the street and block number.');return result
    best=max(counts.values());leaders=[name for name,n in counts.items() if n==best]
    seed=street_key((address or {}).get('street'))
    key=leaders[0] if len(leaders)==1 else seed if seed in leaders else ''
    if not key:
        notes.append('The selection covers several streets. Choose the application street and check its blockfaces.');return result
    fields['street']=key
    numbers=sorted({number//100*100 for p in selected for number,name in [address_parts(p.get('street'))] if number is not None and name==key})
    fields['blocks']='–'.join(map(str,numbers))
    if any(address_parts(p.get('street'))[1] not in {'',key} for p in selected):
        notes.append('Some selected properties have addresses on other streets. Check the corner lots and application street.')
    geoms=[shape(p['geometry']) for p in selected]
    center=unary_union(geoms).centroid
    sx=111320*math.cos(math.radians(center.y));sy=111320
    matrix=[sx,0,0,sy,-center.x*sx,-center.y*sy]
    parcel_points=[affine_transform(g,matrix).representative_point() for g in geoms]
    lines=[]
    for road in roads:
        name=street_key(road.get('name'))
        if not name:continue
        for path in road.get('paths',[]):
            if len(path)<2:continue
            line=affine_transform(LineString([v[:2] for v in path]),matrix)
            if not line.is_empty and line.length>.1:lines.append((name,line))
    main=[line for name,line in lines if name==key]
    if not main:
        notes.append('Street geometry was unavailable for this block. Enter the sides and cross streets, or retry Use map details.');return result
    network=unary_union(main)
    merged=network if network.geom_type=='LineString' else linemerge(network)
    chains=[merged] if merged.geom_type=='LineString' else list(merged.geoms)
    main=min(chains,key=lambda line:sum(line.distance(p) for p in parcel_points))
    # Canonical west-to-east / south-to-north ordering, independent of County digitization.
    start,end=Point(main.coords[0]),Point(main.coords[-1])
    east_west=abs(end.x-start.x)>=abs(end.y-start.y)
    if (end.x<start.x if east_west else end.y<start.y):main=LineString(list(main.coords)[::-1])
    positions=[main.project(p) for p in parcel_points]
    side_signs=[];axes=[]
    for p,pos in zip(parcel_points,positions):
        near=main.interpolate(pos);a=main.interpolate(max(0,pos-5));b=main.interpolate(min(main.length,pos+5))
        dx=b.x-a.x;dy=b.y-a.y;length=math.hypot(dx,dy)
        if not length or near.distance(p)>150:
            notes.append('Some properties are far from the matching street. Confirm the selected blockfaces.');continue
        axis=abs(dx)>=abs(dy);axes.append(axis)
        # The cross product distinguishes physical sides even on a gently curved road.
        offset=(dx*(p.y-near.y)-dy*(p.x-near.x))/length
        if abs(offset)<1:continue
        side_signs.append(1 if offset>0 else -1)
    axis_counts=Counter(axes)
    if len(side_signs)!=len(selected) or not axes or max(axis_counts.values())/len(axes)<.75:
        notes.append('The street bends or the selected properties do not have a clear common side. Confirm the sides of the street.')
    else:
        east_west=axis_counts.most_common(1)[0][0]
        # Direction along the canonical chain may differ locally on a bend.
        mid=main.interpolate(sum(positions)/len(positions));pos=main.project(mid)
        a=main.interpolate(max(0,pos-5));b=main.interpolate(min(main.length,pos+5))
        positive='north' if b.x>=a.x else 'south'
        if not east_west:positive='west' if b.y>=a.y else 'east'
        negative={'north':'south','south':'north','east':'west','west':'east'}[positive]
        side_names={positive if s>0 else negative for s in side_signs}
        fields['sides']=('north and south sides' if east_west else 'east and west sides') if len(side_names)==2 else next(iter(side_names))+' side'
        fields['blockfaces']=str(len(side_names))
    intersections=[]
    for name,line in lines:
        if name==key:continue
        hits=points(main.intersection(line))
        # Small endpoint gaps are common in the County's linework. Never treat a
        # parallel nearby street as a cross street solely because it is close.
        if not hits and main.distance(line)<=2:
            for endpoint in [Point(line.coords[0]),Point(line.coords[-1])]:
                if endpoint.distance(main)<=2:hits.append(nearest_points(main,endpoint)[0])
            for endpoint in [Point(main.coords[0]),Point(main.coords[-1])]:
                if endpoint.distance(line)<=2:hits.append(endpoint)
        for hit in hits:
            pos=main.project(hit);rp=line.project(hit)
            a=main.interpolate(max(0,pos-5));b=main.interpolate(min(main.length,pos+5));dx=b.x-a.x;dy=b.y-a.y;length=math.hypot(dx,dy)
            if not length:continue
            branches=set()
            for sample in [line.interpolate(max(0,rp-12)),line.interpolate(min(line.length,rp+12))]:
                offset=(dx*(sample.y-hit.y)-dy*(sample.x-hit.x))/length
                if abs(offset)>2:branches.add(1 if offset>0 else -1)
            if not branches and (pos<2 or pos>main.length-2) and (rp<2 or rp>line.length-2):
                # A named continuation also defines the end of this street.
                branches={-1,1}
            if not branches:continue
            # A T-junction on the opposite side does not end a one-sided blockface.
            if fields['blockfaces']=='1' and not branches.intersection(side_signs):continue
            if not any(n==name and abs(x-pos)<3 for x,n in intersections):intersections.append((pos,name))
    lo,hi=min(positions),max(positions)
    before=[x for x in intersections if x[0]<=lo+2]
    after=[x for x in intersections if x[0]>=hi-2]
    def endpoint(candidates,last=False):
        if not candidates:return ''
        distance=(max if last else min)(x[0] for x in candidates)
        names={name for pos,name in candidates if abs(pos-distance)<3}
        if len(names)>1:
            notes.append('A junction has more than one street name. Confirm the cross street at that end.');return ''
        return next(iter(names))
    fields['fromStreet']=endpoint(before,True);fields['toStreet']=endpoint(after)
    if fields['fromStreet'] and fields['fromStreet']==fields['toStreet']:
        fields['fromStreet']=fields['toStreet']=''
        notes.append('The street loops back to the same cross street. Confirm the boundary description.')
    if not fields['fromStreet'] or not fields['toStreet']:
        notes.append('A connecting cross street could not be identified at one or both ends. Confirm the missing cross street.')
    if any(lo+2<pos<hi-2 for pos,name in intersections):
        notes.append('The selected properties span an intervening street. Check whether this is one blockface or two opposing blockfaces.')
    fields['description']=description(fields)
    result['notes']=list(dict.fromkeys(notes))
    return result
