"""Build a sourced, interactive cafe map from verified local snapshots."""
import json
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import pandas as pd
from join_a01_poi import ROOT, OUT, distances

def main():
    ref=json.loads((OUT/'dongdaegu_exit_cafes.json').read_text(encoding='utf-8'))
    source=ROOT/'service/data/processed/poi.parquet'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==ref['input_hashes'][source.name]
    poi=pd.read_parquet(source); cafes=poi.loc[poi.cat_s.eq('카페')].drop_duplicates()
    points=ref['exit_points']
    d=np.column_stack([distances(cafes.lat.to_numpy(),cafes.lon.to_numpy(),p['latitude'],p['longitude']) for p in points])
    grouped={}
    for pos in np.where(d.min(axis=1)<=300)[0]:
        r=cafes.iloc[pos];i=int(d[pos].argmin());key=(float(r.lon),float(r.lat))
        grouped.setdefault(key,[]).append({'name':str(r['name']),'branch':str(r['branch']) if pd.notna(r['branch']) else '', 'address':str(r.addr),'exit':points[i]['exit'],'distance':round(float(d[pos,i]))})
    assert sum(map(len,grouped.values()))==41
    raw=ROOT/'data/raw/a01/dongdaegu_osm_roads.json'
    roads=[]
    for w in json.loads(raw.read_text(encoding='utf-8'))['elements']:
        if len(w['geometry'])>1:roads.append({'kind':w['tags']['highway'],'name':w['tags'].get('name',''),'geometry':{'type':'LineString','coordinates':[[p['lon'],p['lat']] for p in w['geometry']]}})
    osm_path=ROOT/'data/raw/a01/dongdaegu_osm.osm'
    osm=ET.parse(osm_path).getroot()
    nodes={e.attrib['id']:[float(e.attrib['lon']),float(e.attrib['lat'])] for e in osm.findall('node')}
    landmark_ids={'404517246','468581498','472262363','1219331357','1219331371'}
    landmarks=[]
    for way in osm.findall('way'):
        if way.attrib['id'] not in landmark_ids:continue
        tags={t.attrib['k']:t.attrib['v'] for t in way.findall('tag')}
        coords=[nodes[n.attrib['ref']] for n in way.findall('nd')]
        assert coords[0]==coords[-1]
        landmarks.append({'name':tags['name'],'osm_id':way.attrib['id'],'geometry':{'type':'Polygon','coordinates':[coords]}})
    assert len(landmarks)==5
    data={'exits':points,'groups':[{'coordinates':list(k),'items':v} for k,v in grouped.items()],'roads':roads,'landmarks':landmarks}
    provenance={'source':'https://www.openstreetmap.org/api/0.6/map?bbox=128.623,35.874,128.633,35.881','retrieved_date':'2026-10-12','license':'ODbL; OpenStreetMap contributors','sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (raw,osm_path)},'landmarks':[{'name':x['name'],'osm_way':x['osm_id']} for x in landmarks],'note':'OSM background labels are not independent confirmation of current business operation.'}
    (OUT/'cafe_map_sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    template=(ROOT/'scripts/dongdaegu-map.template.html').read_text(encoding='utf-8')
    target.write_text(template.replace('__MAP_DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/')),encoding='utf-8')
    assert target.stat().st_size<1000000
    print(f'Cafe records: 41; coordinate groups: {len(grouped)}; road geometries: {len(roads)}; bytes: {target.stat().st_size}')

if __name__=='__main__':main()
