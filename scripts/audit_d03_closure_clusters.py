"""Audit concentrated closures; diagnostic flags only, never training filters."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 old=json.loads((OUT/'error_analysis.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';verify_snapshot_hash(sp,old['hashes']['stores'])
 s=pd.read_parquet(sp);f=s[s.service.eq('일반음식점')&s.category.eq('호프/통닭')&s.ld.dt.year.between(2010,2021)].copy()
 f['event']=f.closed&(f.cd-f.ld).dt.days.between(0,365)
 f['valid_coordinates']=f.lat.between(-90,90)&f.lon.between(-180,180)
 v=f[f.ld.dt.year.between(2017,2018)&f.valid_coordinates].copy()
 assert len(v)==504 and int(v.event.sum())==107
 dates=pd.to_datetime(['2017-07-23','2017-07-26','2018-07-23'])
 v['date_cluster']=v.event&v.cd.isin(dates)
 # Outcome-informed description, not an admission/feature rule.
 v['park_july_candidate']=v.date_cluster&v.ld.dt.month.eq(7)&v.road_addr_raw.fillna('').str.contains('공원순환로',regex=False)
 rawpath=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 cols=['관리번호','개방자치단체코드','인허가일자','폐업일자','업태구분명','영업상태명','상세영업상태명','사업장명','도로명주소']
 raw=pd.read_csv(rawpath,encoding='cp949',usecols=cols,dtype=str)
 raw['_key']=raw['개방자치단체코드'].str.strip()+'|'+raw['관리번호'].str.strip()
 assert raw['_key'].is_unique
 v['_key']=v.org_code.astype(str).str.replace(r'\.0$','',regex=True).str.strip()+'|'+v.mgmt_no.astype(str).str.strip()
 j=v.merge(raw,on='_key',how='left',validate='many_to_one',indicator=True)
 matched=j['_merge'].eq('both')
 check={}
 for col,source in [('ld','인허가일자'),('cd','폐업일자')]:
  t=pd.to_datetime(j[source],errors='coerce');check[col+'_mismatches']=int((matched&~(j[col].eq(t)|(j[col].isna()&t.isna()))).sum())
 check.update(raw_matched=int(matched.sum()),raw_unmatched=int((~matched).sum()),category_mismatches=int((matched&j.category.ne(j['업태구분명'])).sum()))
 annual=[]
 for yr,g in f.groupby(f.ld.dt.year):annual.append({'year':int(yr),'n':len(g),'events':int(g.event.sum()),'pct':float(g.event.mean()*100)})
 summary={'n':len(v),'events':int(v.event.sum()),'actual_pct':float(v.event.mean()*100),'date_cluster_n':int(v.date_cluster.sum()),'park_july_candidate_n':int(v.park_july_candidate.sum()),'candidate_durations':(v.loc[v.park_july_candidate,'cd']-v.loc[v.park_july_candidate,'ld']).dt.days.value_counts().sort_index().to_dict()}
 remaining=v[~v.park_july_candidate];summary['diagnostic_excluding_candidates']={'n':len(remaining),'events':int(remaining.event.sum()),'pct':float(remaining.event.mean()*100)}
 result={'scope':'post-outcome diagnostic, not a new validation/model result','summary':summary,'raw_check':check,'annual_all_coordinates':annual,'closure_date_counts':{str(k.date()):int(n) for k,n in v[v.event].cd.value_counts().items()},'candidate_addresses':v[v.park_july_candidate].road_addr_raw.value_counts().to_dict(),'candidate_raw_statuses':j[j.park_july_candidate]['상세영업상태명'].value_counts().to_dict(),'sources':['https://chimacfestival.co.kr/page/info_history.php','https://thegoodnight.daegu.go.kr/kr/community/community_01.asp?bcate=&board_id=1&gotoPage=98&idx=599&menu=&mode=cont&snm=&srch_Flag=&srch_Word=&subchk='],'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rawpath),'script':snapshot_sha256(Path(__file__))}}
 (OUT/'closure_cluster_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 호프/통닭 폐업 신고 집중 원인 점검','', '2026-10-28. 기존 모델·학습표본·예측값은 변경하지 않았다.','','## 관찰', '',f'- 기존 검증 동일 표본 {len(v)}건, 1년 이내 신고 {int(v.event.sum())}건({v.event.mean()*100:.2f}%).',f'- 2017-07-23/26, 2018-07-23의 신고 {int(v.date_cluster.sum())}건. 그중 허가 월7월·공원순환로 주소 후보 {int(v.park_july_candidate.sum())}건.',f'- 원본 관리번호+자치단체코드 연결 점검: {check}. 원본과 가공본의 기록 일치 여부이며 실제 영업 종료의 진위를 보증하지 않는다.','','[공식 축제 연혁](https://chimacfestival.co.kr/page/info_history.php)과 [대구시 2017 안내](https://thegoodnight.daegu.go.kr/kr/community/community_01.asp?bcate=&board_id=1&gotoPage=98&idx=599&menu=&mode=cont&snm=&srch_Flag=&srch_Word=&subchk=)에서 2017년7월19~23일, 2018년7월18~22일 두류공원 축제 일정 확인. 주소·짧은 허가 기간·폐업 신고일 패턴으로 축제 한시 영업 혼입 가능성을 추론한다. 개별 부스 참가/한시 허가 확정 근거는 아직 없다.','','## 사후 민감도 진단', '',f"위 후보를 가정상 제외하면 {len(remaining)}건 중 {int(remaining.event.sum())}건({remaining.event.mean()*100:.2f}%)이다. **폐업 결과를 보고 만든 후보 조건이라서 모델 성능 개선이나 새 검증 결과로 해석할 수 없다.** 기존21.23%를 오류라며 덮어쓰거나 이 조건으로 학습 데이터를 삭제하지 않았다.",'','## 다음 조치','','상설 음식점의 실패 위험을 목표로 할 경우 한시/행사 인허가를 구분할 필요가 있다. 허가 당시 확인 가능한 한시영업 표시·허가기간·행사 참가 명부를 먼저 확보/확인하고, 폐업일 없이 적용 가능한 기준을 모든 학습·검증기간에 일관되게 정의한 뒤 새 실험을 계획한다. 단순 단기폐업 전체 삭제는 정상 실패 사례까지 제외하므로 하지 않는다. 축제 효과와 일반 영업 실패를 같은 사건으로 취급했을 가능성에 대한 단서이며, 모든 예측 오차가 해결된 것은 아니다.','','## 검증/재현','','504/107 기존 코호트 재현·원본 키 유일성/다대일 연결 검사·날짜/업태 대조. 원본 해시와 상세 집계는 [JSON](closure_cluster_audit.json). `python scripts/audit_d03_closure_clusters.py`. 원본·운영 앱·DB 변경 없음.']
 (OUT/'closure_cluster_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
