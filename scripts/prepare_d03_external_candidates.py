"""Acquire public school preview and prepare land-price join keys; no model adoption."""
import hashlib,json,re,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/d03'
def save(name,obj):
 (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 codes=json.loads((OUT/'daegu_legal_codes.json').read_text(encoding='utf-8'))['codes']
 source=OUT/'building_api_900.json'
 buildings=json.loads(source.read_text(encoding='utf-8'))['results']
 rows=[]
 for r in buildings:
  m=re.fullmatch(r'(.+?) (산)?\s*(\d+)(?:-(\d+))?',r['building_key'])
  if not m or m[1] not in codes:continue
  pnu=codes[m[1]]+('2' if m[2] else '1')+m[3].zfill(4)+(m[4] or '0').zfill(4)
  assert re.fullmatch(r'\d{19}',pnu)
  rows.append({'building_key':r['building_key'],'pnu':pnu})
 assert len({r['pnu'] for r in rows})==len(rows)
 save('land_price_join_candidates.json',{'status':'join_keys_only_not_price_data','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'count':len(rows),'limitation':'Current legal codes; historical parcel division/merger and address continuity unverified. PNU is a parcel, not an individual shop.','rows':rows})
 url='https://open.neis.go.kr/hub/schoolInfo?Type=json&ATPT_OFCDC_SC_CODE=D10&pIndex=1&pSize=1000'
 raw=urllib.request.urlopen(url,timeout=25).read()
 data=json.loads(raw)['schoolInfo']
 total=data[0]['head'][0]['list_total_count']
 rows=data[1]['row']
 fields=['SD_SCHUL_CODE','SCHUL_NM','SCHUL_KND_SC_NM','ORG_RDNMA','FOND_YMD','LOAD_DTM']
 assert len({r['SD_SCHUL_CODE'] for r in rows})==len(rows)
 save('school_info_preview.json',{'source':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'response_sha256':hashlib.sha256(raw).hexdigest(),'reported_total':total,'received':len(rows),'complete':len(rows)==total,'status':'preview_only_not_model_input','limitation':'Unauthenticated sample. Current school addresses do not establish historical location or include all closed schools. Founding date is not address occupancy date.','rows':[{k:r.get(k) for k in fields} for r in rows]})
 print(json.dumps({'land_join_keys':len(buildings),'schools_received':len(rows),'schools_reported_total':total,'trained':False}))
if __name__=='__main__':main()
