"""D-06 ready-to-connect consultation lookup; standard library only."""
from pathlib import Path
import json,math,re,unicodedata
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/d06/delivery/current/consultation_current.json'
def normalized(s):return re.sub(r'[^a-z0-9가-힣]','',unicodedata.normalize('NFKC',str(s)).lower())
def _count(v,label,unit='건'):
 if v is None:return {'value':None,'status':'unavailable','display':f'{label} 정보는 아직 확인되지 않았어요.'}
 f=float(v)
 if not math.isfinite(f) or f<0 or not f.is_integer():return {'value':None,'status':'unavailable','display':f'{label} 정보는 아직 확인되지 않았어요.'}
 return {'value':int(f),'status':'observed','display':f'{label} {int(f):,}{unit}'}
def lookup_franchise(query,data_path=DATA):
 records=json.loads(Path(data_path).read_text(encoding='utf-8-sig'));key=normalized(query)
 if not key:return {'status':'needs_brand','message':'브랜드 이름을 알려주세요.'}
 exact=[r for r in records if r['brand_id']==query or (r.get('brand_name') and normalized(r['brand_name'])==key)]
 if not exact:
  suggestions=[{'brand_id':r['brand_id'],'brand_name':r['brand_name']} for r in records if r.get('brand_name') and key in normalized(r['brand_name'])]
  return {'status':'choose_brand' if suggestions else 'not_found','candidates':suggestions,'message':'어느 브랜드인지 골라주세요.' if suggestions else '현재 준비된 자료에서 이 브랜드를 찾지 못했어요.'}
 if len(exact)>1:return {'status':'choose_brand','candidates':[{'brand_id':r['brand_id'],'brand_name':r['brand_name']} for r in exact]}
 r=exact[0];year=int(r['target_accounting_year']);baseyear=int(r['baseline_accounting_year']);prob=float(r['decline_probability']);last=_count(r['baseline_daegu_stores'],f'{baseyear}년 말 대구 가맹점','개');prev=_count(r['previous_daegu_stores'],f'{int(r["previous_accounting_year"])}년 말 대구 가맹점','개')
 flow='줄었어요' if last['value']<prev['value'] else '늘었어요' if last['value']>prev['value'] else '같은 수준이었어요'
 national={k:_count(r.get(k),label) for k,label in [('national_frcsCnt','전국 가맹점'),('national_newFrcsRgsCnt','전국 신규 개점'),('national_ctrtEndCnt','전국 계약 종료'),('national_ctrtCncltnCnt','전국 계약 해지')]}
 national['national_frcsCnt']=_count(r.get('national_frcsCnt'),'전국 가맹점','개')
 return {'status':'ok','brand_id':r['brand_id'],'brand_name':r.get('brand_name'),'industry':r['industry'],'title':f'{year}년 말 가맹점 수 전망','generated_date':r['generated_date'],'observed':{'previous':prev,'baseline':last,'regional_report_year':int(r['regional_report_year']),'national_report_year':int(r['national_report_year']),'national_scope':'전국','national':national},'forecast':{'target_accounting_year':year,'baseline_accounting_year':baseyear,'decline_probability':prob,'period_text':f'{baseyear}년 말 대비 {year}년 말 감소 여부','meaning':'generation-date next12months forecast is not available'},'message':f'{baseyear}년 말 대구 가맹점은 {last["value"]}개로, 전년과 비교하면 {flow}. 과거 자료로 계산한 {year}년 말 감소 가능성은 약 {prob:.0%}예요. 실제 매장 수는 달라질 수 있으니 최신 매장 현황과 계약 조건도 함께 살펴보면 좋겠어요.'}
if __name__=='__main__':
 import sys
 print(json.dumps(lookup_franchise(' '.join(sys.argv[1:])),ensure_ascii=False,indent=2))
