"""Outcome-independent event-address marker audit; no model fitting."""
import json,re
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'docs/d03';prior=json.loads((out/'area_complete.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 verify_snapshot_hash(sp,prior['hashes']['stores']);verify_snapshot_hash(rp,prior['hashes']['raw'])
 st=pd.read_parquet(sp,columns=['service','org_code','mgmt_no','ld']);f=st[st.service.eq('일반음식점')].copy()
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','지번주소','도로명주소','사업장명'])
 r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 f['key']=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no;assert f.key.is_unique
 rr=r.set_index('key');matched=f.key.isin(rr.index)
 for c in ['지번주소','도로명주소','사업장명']:f[c]=f.key.map(rr[c]).fillna('')
 normalize=lambda s:s.str.replace(r'\s+','',regex=True)
 address=normalize(f['지번주소']+' '+f['도로명주소']);text=address+' '+normalize(f['사업장명'])
 explicit=address.str.contains('행사장|축제장',regex=True);broad=text.str.contains('축제|페스티벌|행사장|한시영업|임시영업|팝업',regex=True)
 f['marker']='no_marker';f.loc[broad,'marker']='review_keyword';f.loc[explicit,'marker']='explicit_address';f.loc[~matched,'marker']='unmatched'
 assert f.loc[explicit,'marker'].eq('explicit_address').all()
 f['year']=f.ld.dt.year.astype('Int64').astype('string').fillna('unknown')
 totals={str(k):int(v) for k,v in f.marker.value_counts().items()};assert sum(totals.values())==len(f)
 years=f.groupby(['year','marker']).size().reset_index(name='n');assert years.n.sum()==len(f)
 rows=f[f.marker.isin(['explicit_address','review_keyword'])][['key','year','marker','지번주소','도로명주소','사업장명']]
 output={'scope':'all general restaurants; address/name-only descriptive markers; no outcome read','n':len(f),'totals':totals,'years':json.loads(years.to_json(orient='records',force_ascii=False)),'candidates':json.loads(rows.to_json(orient='records',force_ascii=False)),'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'event_marker_plan.md')}}
 (out/'event_markers.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 전체 일반음식점 행사 표기 점검','','폐업 상태/날짜/기간을 읽지 않고 주소·상호로만 후보를 분류했다. 법적 한시허가 여부나 과거 정보 가용성을 확정하지 않는다.','',f'전체 {len(f):,}건.','', '| 분류 | 건수 |','| --- | ---: |']
 for k,n in totals.items():lines.append(f'| {k} | {n} |')
 lines+=['','explicit_address는 주소의 행사장/축제장 직접 표기, review_keyword는 넓은 키워드 후보다. no_marker는 행사 여부 미확인이며 상설점포 확정이 아니다. 원본 미연결은 unmatched로 보존한다.','','## 연도별 분포','','| 개업연도 | 분류 | 건수 |','| --- | --- | ---: |']
 for q in output['years']:
  if q['marker'] in ['explicit_address','review_keyword']:lines.append(f"| {q['year']} | {q['marker']} | {q['n']} |")
 lines+=['','규칙은 전체 연도 동일 적용. 원본 해시·키 유일성·합계 검사 통과. 후보 키와 근거 주소는 JSON에 보존. 이 결과로 행을 삭제하거나 성능 개선을 주장하지 않는다. 새 모델 평가 전 분류 오탐 확인과 별도 평가계획이 필요하다.']
 (out/'event_markers.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'n':len(f),'totals':totals,'review_examples':output['candidates'][:5]},ensure_ascii=False))
if __name__=='__main__':main()
