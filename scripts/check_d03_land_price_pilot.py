"""Small historical land-price availability pilot; no model fitting."""
import json,urllib.request,urllib.parse,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
def main():
 env={}
 for l in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
  if '=' in l and not l.lstrip().startswith('#'):
   k,v=l.split('=',1);env[k.strip()]=v.strip().strip(chr(34)).strip(chr(39))
 key=env.get('VWORLD_API_KEY','')
 if not key:raise SystemExit('VWORLD_API_KEY missing')
 candidates=json.loads((ROOT/'docs/d03/land_price_join_candidates.json').read_text(encoding='utf-8'))['rows']
 chosen=[];seen=set()
 for r in candidates:
  district=r['pnu'][:5]
  if district not in seen:chosen.append(r);seen.add(district)
  if len(chosen)==3:break
 years=[2012,2014,2016,2019,2020,2022,2024]
 path=ROOT/'docs/d03/land_price_pilot.json'
 results=[]
 for r in chosen:
  for year in years:
   q={'key':key,'pnu':r['pnu'],'stdrYear':year,'format':'json','numOfRows':100,'pageNo':1}
   if env.get('VWORLD_DOMAIN'):q['domain']=env['VWORLD_DOMAIN']
   row={**r,'requested_year':year}
   try:
    d=json.loads(urllib.request.urlopen('https://api.vworld.kr/ned/data/getIndvdLandPriceAttr?'+urllib.parse.urlencode(q),timeout=20).read())
    b=d.get('indvdLandPrices',{})
    fields=b.get('field',[]);fields=[fields] if isinstance(fields,dict) else fields
    selected=[{k:x.get(k) for k in ['pnu','stdrYear','stdrMt','pblntfDe','pblntfPclnd','lastUpdtDt']} for x in fields]
    valid=all(str(x.get('pnu'))==r['pnu'] and str(x.get('stdrYear'))==str(year) for x in selected)
    code=b.get('resultCode')
    row.update(status='ok' if valid and code in ('',None,'0','00','INFO-000') and 'totalCount' in b else 'invalid_or_api_error',result_code=code,total=b.get('totalCount'),items=selected)
   except Exception as e:row.update(status='request_error',error_type=type(e).__name__,http_code=getattr(e,'code',None))
   results.append(row)
   report={'retrieved_at':datetime.now(timezone.utc).isoformat(),'selection':'First parcel in each of first 3 districts in existing sorted 900-parcel candidates; availability only, not representative.','source':'https://www.data.go.kr/data/15124014/openapi.do','endpoint':'https://api.vworld.kr/ned/data/getIndvdLandPriceAttr','limitations':['Current parcel identity; historical splits/mergers unverified.','Use publication date before prediction date, not reference year alone.','Last update may indicate retrospective corrections; original vintage unverified.','No model training or performance claim.'],'results':results}
   path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
   time.sleep(.15)
 print(json.dumps({'queries':len(results),'ok':sum(r['status']=='ok' for r in results),'nonempty':sum(bool(r.get('items')) for r in results),'rows':sum(len(r.get('items',[])) for r in results)}))
if __name__=='__main__':main()
