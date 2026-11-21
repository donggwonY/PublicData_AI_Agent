"""D-06 consultation lookup including brands without latest count observations."""
from pathlib import Path
import json,re,unicodedata
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'docs/d06/delivery/revised/brand_registry.json'
def normalized(s):return re.sub(r'[^a-z0-9가-힣]','',unicodedata.normalize('NFKC',str(s)).lower())
def lookup_franchise(query,data_path=DATA):
 records=json.loads(Path(data_path).read_text(encoding='utf-8-sig'));key=normalized(query)
 if not key:return {'status':'needs_brand','message':'브랜드 이름을 알려주세요.'}
 hits=[r for r in records if r['brand']==query or (r.get('brand_name') and normalized(r['brand_name'])==key)]
 if len(hits)!=1:
  candidates=hits or [r for r in records if r.get('brand_name') and key in normalized(r['brand_name'])]
  return {'status':'choose_brand' if candidates else 'not_found','candidates':[{'brand_id':r['brand'],'brand_name':r.get('brand_name')} for r in candidates],'message':'브랜드를 골라주세요.' if candidates else '현재 자료에서 브랜드를 찾지 못했어요.'}
 r=hits[0];year=int(r['last_observed_accounting_year']);count=int(r['last_observed_stores']);status=r['status'];prob=r.get('decline_probability')
 observed={'last_observed_accounting_year':year,'last_observed_daegu_stores':count,'count_source':r['count_source'],'industry':r.get('industry')};forecast=None
 observed['history']=r.get('count_history',[])
 observed['permit_support']=r.get('permit_support')
 observed['national_report_year']=r.get('national_report_year')
 observed['national_scope']='전국'
 observed['national']={k:{'value':r.get(k),'status':'observed' if r.get(k) is not None else 'unavailable'} for k in ['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt']}
 if status in ['current_projection','two_year_projection']:
  assert prob is not None
  baseline=int(r.get('baseline_accounting_year') or year);horizon=int(r.get('forecast_horizon_years') or 1)
  forecast={'target_accounting_year':2026,'baseline_accounting_year':baseline,'horizon_years':horizon,'model_kind':r.get('model_kind'),'decline_probability':float(prob),'period_text':f'{baseline}년 말 대비2026년 말 감소 여부'}
  missing='2025년 말 수치는 아직 확인되지 않아, 2024년 말 자료에서 2년 뒤를 예측하는 별도 모델을 사용했어요. ' if status=='two_year_projection' else ''
  if r.get('model_kind')=='two_year_hgb_permit_support':missing='2025년 공식 가맹점 수는 확인되지 않아, 2024년 공식 수치와 2025년 인허가 활동을 함께 사용한 별도 2년 모델이에요. 인허가 활동은 공식 가맹점 수를 대신하는 값이 아니에요. '
  message=f'{year}년 말 대구 가맹점은 {count}개로 확인돼요. {missing}이 자료를 바탕으로 계산한 2026년 말 감소 가능성은 약 {float(prob):.0%}예요. 최신 매장 현황과 계약 조건도 함께 살펴보면 좋겠어요.'
 elif status=='latest_count_unavailable':message=f'마지막으로 확인된 {year}년 말 대구 가맹점은 {count}개예요. 최신 연도 매장 수가 확인되지 않아 현재 전망은 제공하지 않아요.'
 elif status=='below_three_stores':message=f'{year}년 말 대구 가맹점은 {count}개예요. 이번 모델은3개 이상 브랜드를 대상으로 해서 예측 대신 확인된 매장 수를 안내해요.'
 else:message=f'{year}년 말 대구 가맹점은 {count}개예요. 비교할 전년도 기록이 부족해 현재 전망은 확인하기 어려워요.'
 return {'status':'ok','data_status':status,'brand_id':r['brand'],'brand_name':r.get('brand_name'),'generated_date':r['generated_date'],'observed':observed,'forecast':forecast,'message':message,'dataset':'d06_revised_missing_counts_20261121'}
if __name__=='__main__':
 import sys
 print(json.dumps(lookup_franchise(' '.join(sys.argv[1:])),ensure_ascii=False,indent=2))
