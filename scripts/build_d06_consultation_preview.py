"""Prepare historical D-06 consultation examples without turning missing data into zeros."""
from pathlib import Path
import json,math
import pandas as pd

def display_count(value,label,unit='건'):
 try:v=float(value)
 except (TypeError,ValueError):return dict(value=None,status='unavailable',text=f'{label} 정보는 아직 확인되지 않았어요.')
 if not math.isfinite(v) or v<0 or not v.is_integer():return dict(value=None,status='unavailable',text=f'{label} 정보는 아직 확인되지 않았어요.')
 return dict(value=int(v),status='observed',text=f'{label} {int(v):,}{unit}')

def main():
 P=Path('docs/d06/decline/additional');cases=pd.read_csv(P/'consultation_cases.csv');out=[]
 for r in cases.to_dict('records'):
  known=all(pd.notna(r.get(k)) for k in ['previous','last'])
  change='줄었어요' if known and r['last']<r['previous'] else '늘었어요' if known and r['last']>r['previous'] else '같은 수준이었어요' if known else '변화를 확인하기 어려워요'
  signal='예측에서도 감소 가능성을 함께 살펴볼 신호가 나타났어요.' if r['probability']>=.5 else '예측에서 감소 신호가 강하게 나타나지는 않았지만, 매장 수는 달라질 수 있어요.'
  fields=[display_count(r.get('previous'),'2022년 대구 가맹점 수','개'),display_count(r.get('last'),'2023년 대구 가맹점 수','개')]
  for key,label in [('national_newFrcsRgsCnt','전국 신규 개점'),('national_ctrtEndCnt','전국 계약 종료'),('national_ctrtCncltnCnt','전국 계약 해지')]:fields.append(display_count(r.get(key),label))
  out.append(dict(brand=r['brandNm'],context='2024년 예측을 확인하는 과거 연구 사례예요. 현재 상태를 뜻하지 않아요.',regional_accounting_years=[2022,2023],national_report_year=2023,national_scope='전국 자료이며 대구 건수가 아닙니다.',message=f'당시 대구 가맹점 수는 {change}. {signal} 관심 있는 브랜드라면 최신 매장 현황과 계약 조건도 함께 살펴보면 좋겠어요.',fields=fields,source='공정거래위원회 가맹정보 API',limitations='실제 공개 시점은 확인 중이며, 계약 종료·해지가 사업 실패를 뜻하지는 않습니다.'))
 assert display_count(0,'계약 해지')['status']=='observed'
 for v in [None,float('nan'),float('inf'),'',-1]:assert display_count(v,'계약 해지')['value'] is None
 assert all('actual' not in r for r in out)
 (P/'consultation_preview.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 # Clearly marked display-only cases; never model observations.
 demos=[dict(kind='표시 기능 검증용 입력',input='0',output=display_count(0,'계약 해지')),dict(kind='표시 기능 검증용 입력',input='missing',output=display_count(None,'계약 해지'))]
 (P/'missing_display_checks.json').write_text(json.dumps(demos,ensure_ascii=False,indent=2),encoding='utf-8');print('4 historical previews generated; zero/missing/invalid checks passed. No future actual outcomes included.')
if __name__=='__main__':main()
