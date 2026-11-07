"""Small cached building-ledger pilot. No model input adoption."""
import json,re,urllib.request,urllib.parse,time
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
f=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
f=f[f.service.eq('일반음식점') & f.building_key.str.startswith('대구광역시 수성구 두산동 ',na=False)].copy()
keys=f.building_key.drop_duplicates().sort_values().sample(n=20,random_state=7).sort_values().tolist()
key=next(l.split('=',1)[1].strip().strip('\"').strip("'") for l in (ROOT/'.env.data-go-kr').read_text(encoding='utf-8-sig').splitlines() if l.startswith('DATA_GO_KR_SERVICE_KEY='))
path=ROOT/'docs/d03/building_api_pilot.json'
old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
cache={r['building_key']:r for r in old.get('results',[]) if r.get('status')=='ok'}
results=[]
for k in keys:
 if k in cache: results.append(cache[k]);continue
 m=re.fullmatch(r'대구광역시 수성구 두산동 (산)?\s*(\d+)(?:-(\d+))?',k)
 if not m:results.append({'building_key':k,'status':'unparsed'});continue
 q=urllib.parse.urlencode({'serviceKey':urllib.parse.unquote(key),'sigunguCd':'27260','bjdongCd':'11100','platGbCd':'1' if m[1] else '0','bun':m[2].zfill(4),'ji':(m[3] or '0').zfill(4),'numOfRows':100,'pageNo':1,'_type':'json'})
 r={'building_key':k}
 try:
  d=json.loads(urllib.request.urlopen('https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?'+q,timeout=15).read())['response']
  h=d.get('header',{});b=d.get('body',{});it=b.get('items',{});it=it.get('item',[]) if isinstance(it,dict) else [];it=[it] if isinstance(it,dict) else it
  r.update(status='ok' if str(h.get('resultCode'))=='00' else 'api_error',code=h.get('resultCode'),total=int(b.get('totalCount',0)),items=[{n:x.get(n) for n in ['platPlc','sigunguCd','bjdongCd','bun','ji','mainPurpsCdNm','grndFlrCnt','ugrndFlrCnt','useAprDay','totArea','crtnDay']} for x in it])
 except Exception as e:r.update(status='request_error',error_type=type(e).__name__,http_code=getattr(e,'code',None))
 results.append(r)
 path.write_text(json.dumps({'scope':'두산동 599개 고유건물 중 정렬 후 seed7 단순무작위20; 폐업 결과 미사용','results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 time.sleep(.15)
counts={'requested':len(results),'responses':sum(r['status']=='ok' for r in results),'none':sum(r.get('total')==0 for r in results),'single':sum(r.get('total')==1 for r in results),'multiple':sum(r.get('total',0)>1 for r in results)}
singles=[r for r in results if r.get('total')==1]
valid_date=sum(bool(re.fullmatch(r'\d{8}',str(r['items'][0].get('useAprDay','')))) and pd.notna(pd.to_datetime(str(r['items'][0]['useAprDay']),format='%Y%m%d',errors='coerce')) for r in singles)
counts['single_valid_approval_date']=valid_date
report={'scope':'2026-11-07 두산동 소재 일반음식점 고유건물599개 중 무작위20(seed7), 결과 미사용 표집. 대구 전체 대표표본 아님.','counts':counts,'results':results}
path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# 건축물대장 소량 연결 점검','',report['scope'],'',json.dumps(counts,ensure_ascii=False),'','주소 필지단위 조회이며 점포 호실 연결 아님. 다중 건물은 임의 첫 행 선택하지 않음. 현재 대장: 과거의 용도·층수·면적 및 생존 건물 선택편향 미검증. 사용승인일도 동일 건물인지 확인 후 기준일 이전 조건으로만 검토. 건물 연면적을 점포면적으로 대체하지 않음. 현재는 연결성 점검이며 모델 입력 채택·학습·DB 적재 없음.','', '출처: https://www.data.go.kr/data/15134735/openapi.do']
(ROOT/'docs/d03/building_api_pilot.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(counts,ensure_ascii=False))
