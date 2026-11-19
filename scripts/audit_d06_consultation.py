from pathlib import Path
import json
import numpy as np
import pandas as pd
P=Path('docs/d06/decline/additional');d=pd.read_csv(P/'predictions.csv');x=pd.read_csv(P.parent/'eligible_cells.csv');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet')
z=d[(d.model=='additional')&(d.year==2024)].merge(x,on=['brand','year','label'],validate='one_to_one')
meta=j[j.source_report_year==2024][['brandMnno','brandNm','acntgYr','frcsCnt']].rename(columns={'brandMnno':'brand','frcsCnt':'source_count','acntgYr':'feature_accounting_year'})
z=z.merge(meta,on='brand',how='left',validate='many_to_one');z['source_count_matches']=z.source_count==z['last'];assert (pd.to_numeric(z.feature_accounting_year.dropna())==2023).all();z[~z.source_count_matches].to_csv(P/'source_count_discrepancies.csv',index=False)
cols=['national_frcsCnt','national_newFrcsRgsCnt','national_ctrtEndCnt','national_ctrtCncltnCnt']
n=j[j.source_report_year==2023][['brandMnno']+cols].rename(columns={'brandMnno':'brand'});z=z.merge(n,on='brand',how='left',validate='many_to_one')
z['signal']=z.probability>=.5;z['case_type']=np.select([z.signal & (z.label==1),z.signal & (z.label==0),~z.signal & (z.label==1)],['signal_and_decline','signal_without_decline','decline_without_signal'],default='no_signal_no_decline')
# Fixed review selection: one median-probability case per outcome, known name and national records.
chosen=[]
for typ,g in z.groupby('case_type'):
 g=g[g.brandNm.notna()&g.national_frcsCnt.notna()&g.source_count_matches].sort_values(['probability','brand']);assert len(g)>0;chosen.append(g.iloc[len(g)//2])
c=pd.DataFrame(chosen);c.to_csv(P/'consultation_cases.csv',index=False)
summary=dict(year=2024,total=len(z),source_count_discrepancies=int((z.source_count.notna() & ~z.source_count_matches).sum()),source_rows_missing=int(z.source_count.isna().sum()),known_name=int(z.brandNm.notna().sum()),national_records=int(z.national_frcsCnt.notna().sum()),selection='one median probability case per outcome among records with name and national counts, retrospective illustration not representative performance',reference_threshold=.5,case_counts=z.case_type.value_counts().to_dict(),historical_only=True)
(P/'consultation_audit.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
lines=['# 상담 참고정보 사례 검증','', '2026-11-19. 2024 회계연도에 대한 과거 예측 사례이며 현재 브랜드 상태나 앞으로1년의 예측이 아니다.2024 기준년도 지역 자료는2023 회계연도, 전국 계약 통계는 그보다1개 기준년도 이전인2023 자료를 사용했다. 실제 과거 공개일 미확인으로 당시 실시간 상담 가능성을 확정하지 않는다.','', '## 선정과 대조','', '전체813건에서 기존 매출 API의 과거 점포 수와 별도 지역 API를 대조했다. 불일치 행은 source_count_discrepancies.csv에 기록하고 이번 상담 예시에서는 제외했다. 모델 평가 표본에서 삭제한 것은 아니다. 두 API의 갱신·집계 차이는 원인 미확인이며 운영 입력을 혼용하기 전에 해결해야 한다. 예측 기준0.5에서 맞은 경고·틀린 경고·놓친 감소·감소 없는 비경고 네 유형을 나눈 뒤, 이름 및 전국 기록이 연결된 사례 중 확률 중앙 순서의 브랜드를 각1개 선택했다. 결과를 잘 보이게 하는 성공 사례만 고르지 않았다. 이4개 사례는 전체 품질의 추정 표본이 아니다.','']
for a in c.itertuples():
 lines += [f'### {a.brandNm} ({a.brand})',f'- 업종: {a.industry}; 사례 유형: {a.case_type}.',f'- 당시 대구 가맹점: 2022년 {int(a.previous)}개 → 2023년 {int(a.last)}개.',f'- 연구 모델의 2024년 감소 확률: {a.probability:.1%}.',f'- 전국 2023 기준년도 통계: 신규 {int(a.national_newFrcsRgsCnt)}건, 계약 종료 {int(a.national_ctrtEndCnt)}건, 해지 {int(a.national_ctrtCncltnCnt)}건. 대구 사건 수로 해석하지 않는다.',f'- 사후 검증용 실제 2024년 대구 가맹점 수: {int(a.actual)}개. 이 값은 상담 입력에 사용하지 않는다.','- 상담 확인 사항: 대구 점포 수 흐름과 전국 계약 변동이 서로 같은 방향인지, 본사 설명과 최신 정보공개서를 추가 확인한다. 계약 종료·해지는 사업 실패나 대구 점포 감소 원인으로 단정하지 않는다.','']
lines+=['## 활용 판단','', '예측·대구 과거 수치·전국 계약 변동을 구분해 나란히 제시하는 상담 구조는 구성 가능하다. 다만 이 검증은 자료 대조이며 실제 사용자 평가나 LLM 상담 응답 검증은 아니다. 전국 자료를 대구 자료로 바꾸어 설명하거나, 특정 변수가 예측의 원인이라고 설명하지 않는다. 별도 기여도 검증 없이 수치 나열을 모델 설명으로 부르지 않는다.','', '실제 상담에서는 사후 결과를 숨기고 예측 대상 기간과 자료 기준일을 표시해야 한다. 자료가 빠진 브랜드는 누락이라고 밝힌다. 낮은 확률을 안전·추천으로 표현하지 않는다. 브랜드별 현재 경고를 게시하거나 운영 DB·앱을 변경하지 않았다. 60% 등 시험용 문턱 하나의 미달을 서비스 부적합 근거로 사용하지 않는다.','', '재현: scripts/audit_d06_consultation.py. 다음 구현 전 확인사항은 최신 입력 생성 및 공개 시점 확인, 상담 도구의 출처·기간·누락 반환, 실제 응답의 수치 일치 검증이다.']
(P/'consultation_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(summary));print(c[['brandNm','case_type','previous','last','actual','probability']].to_string(index=False))
