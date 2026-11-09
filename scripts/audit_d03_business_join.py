"""Current-name join feasibility; never asserts historical boundary validity."""
import json,re
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 d=json.loads((OUT/'business_yearbooks_normalized.json').read_text(encoding='utf-8'));f=pd.read_parquet(ROOT/'service/data/processed/stores.parquet');m=pd.read_parquet(ROOT/'service/data/processed/legal_admin_map.parquet')
 rows=d['local_source_rows'];results=[]
 for gu in ['달성군','수성구']:
  labels={r['area_label'] for r in rows if r['district']==gu};g=f[f.gu.eq(gu)].copy();mapping={};ambiguous=[]
  for dong in g.dong.dropna().unique():
   if gu=='달성군':
    label=re.sub(r'(읍|면)$','',str(dong));candidates=[label] if label in labels else []
   else:
    candidates=sorted(set(m[(m.gu==gu)&(m.legal_dong==dong)].admin_dong.dropna().astype(str)))
    candidates=[x for x in candidates if x in labels]
   mapping[dong]=candidates[0] if len(candidates)==1 else None
   if len(candidates)>1:ambiguous.append({'legal_dong':dong,'candidate_admin_dongs':candidates,'permit_rows':int(g.dong.eq(dong).sum())})
  matched=g.dong.map(mapping).notna();latest=max(r['edition_year'] for r in rows if r['district']==gu)
  latest_rows=[r for r in rows if r['district']==gu and r['edition_year']==latest]
  results.append({'district':gu,'permit_rows':len(g),'unique_current_area_match':int(matched.sum()),'unmatched_or_ambiguous':int((~matched).sum()),'current_name_mapping':{str(k):v for k,v in mapping.items()},'ambiguous':ambiguous,'latest_edition':latest,'latest_local_rows':len(latest_rows),'historically_ready_rows':0,'blocking_checks':['Actual publication date unverified','Local-area reference year inferred only','Historical area boundary/location continuity unverified']})
 report={'status':'feasibility_only_not_joined_model_input','districts':results,'rules':['Do not pick maximum share for a legal dong split across administrative dongs.','Dalseong 읍/면 suffix normalization only, not proof of unchanged historical boundary.','Preserve unidentified rows, never silently fill zero.','Current-name match is not historical join validity.']}
 (OUT/'business_join_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 사업체 통계 지역명 연결 점검','','현재 이름 연결 가능성만 확인. 과거 경계와 공표일은 미검증, 모델 입력 생성 없음.','','|지역|인허가 행|현재이름 단일연결|모호/미연결|','|---|---:|---:|---:|']
 for r in results:lines.append(f"|{r['district']}|{r['permit_rows']}|{r['unique_current_area_match']}|{r['unmatched_or_ambiguous']}|")
 lines+=['','수성구 법정동이 여러 행정동으로 나뉘는 경우 최대비중 하나를 강제로 선택하지 않음. 달성군 읍/면 표기 정규화는 행정경계 불변 증명이 아님. 모든 자료는 공표일·기준연도·경계 확인 전 과거예측용으로 보류.']
 (OUT/'business_join_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
