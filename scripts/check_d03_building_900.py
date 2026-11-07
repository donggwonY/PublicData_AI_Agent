"""Small cached building-ledger pilot. No model input adoption."""
import json,re,urllib.request,urllib.parse,time
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
f=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
f=f[f.service.eq('일반음식점')].copy()
codes=json.loads((ROOT/'docs/d03/daegu_legal_codes.json').read_text(encoding='utf-8'))['codes']
parsed={}
for k in f.building_key.dropna().unique():
 m=re.fullmatch(r'(.+?) (산)?\s*(\d+)(?:-(\d+))?',k)
 if m and m[1] in codes:parsed[k]=(codes[m[1]],m[2],m[3],m[4])
u=f[f.building_key.isin(parsed)].drop_duplicates('building_key').sort_values('building_key')
keys=[]
for gu,g in u.groupby('gu'):keys.extend(g.sample(n=min(100,len(g)),random_state=7).building_key.tolist())
keys=sorted(keys)
print('eligible_buildings',len(u),'sample',len(keys),flush=True)
key=next(l.split('=',1)[1].strip().strip('\"').strip("'") for l in (ROOT/'.env.data-go-kr').read_text(encoding='utf-8-sig').splitlines() if l.startswith('DATA_GO_KR_SERVICE_KEY='))
path=ROOT/'docs/d03/building_api_900.json'
old=json.loads((path if path.exists() else ROOT/'docs/d03/building_api_270.json').read_text(encoding='utf-8'))
cache={r['building_key']:r for r in old.get('results',[]) if r.get('status')=='ok'}
results=[]
for k in keys:
 if k in cache: results.append(cache[k]);continue
 code,mountain,bun,ji=parsed[k]
 q=urllib.parse.urlencode({'serviceKey':urllib.parse.unquote(key),'sigunguCd':code[:5],'bjdongCd':code[5:],'platGbCd':'1' if mountain else '0','bun':bun.zfill(4),'ji':(ji or '0').zfill(4),'numOfRows':100,'pageNo':1,'_type':'json'})
 r={'building_key':k}
 try:
  d=json.loads(urllib.request.urlopen('https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?'+q,timeout=15).read())['response']
  h=d.get('header',{});b=d.get('body',{});it=b.get('items',{});it=it.get('item',[]) if isinstance(it,dict) else [];it=[it] if isinstance(it,dict) else it
  r.update(status='ok' if str(h.get('resultCode'))=='00' else 'api_error',code=h.get('resultCode'),total=int(b.get('totalCount',0)),items=[{n:x.get(n) for n in ['platPlc','sigunguCd','bjdongCd','bun','ji','mainPurpsCdNm','grndFlrCnt','ugrndFlrCnt','useAprDay','totArea','crtnDay']} for x in it])
 except Exception as e:r.update(status='request_error',error_type=type(e).__name__,http_code=getattr(e,'code',None))
 results.append(r)
 path.write_text(json.dumps({'scope':'두산동 599개 고유건물 중 정렬 후 seed7 단순무작위20; 폐업 결과 미사용','results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 time.sleep(.15)
 if len(results)%100==0: print('saved',len(results),flush=True)
counts={'requested':len(results),'responses':sum(r['status']=='ok' for r in results),'none':sum(r.get('total')==0 for r in results),'single':sum(r.get('total')==1 for r in results),'multiple':sum(r.get('total',0)>1 for r in results)}
singles=[r for r in results if r.get('total')==1]
valid_date=sum(bool(re.fullmatch(r'\d{8}',str(r['items'][0].get('useAprDay','')))) and pd.notna(pd.to_datetime(str(r['items'][0]['useAprDay']),format='%Y%m%d',errors='coerce')) for r in singles)
counts['single_valid_approval_date']=valid_date
report={'scope':'2026-11-07 주소코드 연결 가능 건물 중 구군별 최대100곳 무작위(seed7). 균등구군표집으로 대구 전체 대표비율 아님.','counts':counts,'results':results}
path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# 건축물대장 소량 연결 점검','',report['scope'],'',json.dumps(counts,ensure_ascii=False),'','주소 필지단위 조회이며 점포 호실 연결 아님. 다중 건물은 임의 첫 행 선택하지 않음. 현재 대장: 과거의 용도·층수·면적 및 생존 건물 선택편향 미검증. 사용승인일도 동일 건물인지 확인 후 기준일 이전 조건으로만 검토. 건물 연면적을 점포면적으로 대체하지 않음. 현재는 연결성 점검이며 모델 입력 채택·학습·DB 적재 없음.','', '출처: https://www.data.go.kr/data/15134735/openapi.do']
(ROOT/'docs/d03/building_api_900.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(counts,ensure_ascii=False))
