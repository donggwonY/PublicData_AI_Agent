"""Cached, bounded collection of historical public land prices."""
import json,urllib.request,urllib.parse,time,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 env={}
 for l in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
  if '=' in l and not l.lstrip().startswith('#'):
   k,v=l.split('=',1);env[k.strip()]=v.strip().strip(chr(34)).strip(chr(39))
 key=env['VWORLD_API_KEY'];path=OUT/'land_prices_900.json'
 candidates=json.loads((OUT/'land_price_join_candidates.json').read_text(encoding='utf-8'))['rows']
 cache={r['pnu']:r for r in json.loads(path.read_text(encoding='utf-8')).get('results',[]) if r['status']=='ok'} if path.exists() else {}
 def fetch(r):
  if r['pnu'] in cache:return cache[r['pnu']]
  result={**r};items=[]
  try:
   for page in range(1,11):
    q={'key':key,'pnu':r['pnu'],'format':'json','numOfRows':100,'pageNo':page}
    if env.get('VWORLD_DOMAIN'):q['domain']=env['VWORLD_DOMAIN']
    b=json.loads(urllib.request.urlopen('https://api.vworld.kr/ned/data/getIndvdLandPriceAttr?'+urllib.parse.urlencode(q),timeout=20).read()).get('indvdLandPrices',{})
    if b.get('resultCode') not in ('',None,'0','00') or 'totalCount' not in b:raise ValueError('API response error')
    total=int(b['totalCount']);f=b.get('field',[]);f=[f] if isinstance(f,dict) else f
    assert all(str(x.get('pnu'))==r['pnu'] for x in f)
    items.extend({k:x.get(k) for k in ['pnu','stdrYear','stdrMt','pblntfDe','pblntfPclnd','lastUpdtDt']} for x in f)
    if len(items)>=total:break
    if not f:raise ValueError('Incomplete response')
   assert len(items)==total
   result.update(status='ok',total=total,items=items)
  except Exception as e:result.update(status='request_error',error_type=type(e).__name__,http_code=getattr(e,'code',None))
  time.sleep(.4);return result
 results=[]
 def save():
  path.write_text(json.dumps({'retrieved_at':datetime.now(timezone.utc).isoformat(),'source':'https://www.data.go.kr/data/15124014/openapi.do','scope':'Existing 900 parcel sample, all returned historical reference years; current parcel identifiers, retrospective revisions possible.','results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with ThreadPoolExecutor(max_workers=int(os.environ.get("D03_FETCH_WORKERS","1"))) as pool:
  for r in pool.map(fetch,candidates):
   results.append(r)
   if len(results)%100==0:save();print('saved',len(results),flush=True)
 save();print('ok',sum(r['status']=='ok' for r in results),'rows',sum(len(r.get('items',[])) for r in results),flush=True)
if __name__=='__main__':main()
