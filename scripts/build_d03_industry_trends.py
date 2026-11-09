"""Non-overlapping district/industry permit trends for descriptive use."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 src=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(src);meta=json.loads((src.parent/'meta.json').read_text(encoding='utf-8'));ref=pd.Timestamp(meta['reference_date'])
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())
 quality={'source_rows':len(f),'date_exclusions':int(bad.sum())};f=f[~bad].copy();f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'});f['gu']=f.gu.fillna('지역미상')
 rows=[];checks=[]
 for date in [pd.Timestamp(2021,1,1),pd.Timestamp(2023,1,1),ref]:
  start=date-pd.Timedelta(days=365)
  a=f.ld.le(date)&(f.cd.isna()|f.cd.gt(date));o=f.ld.gt(start)&f.ld.le(date);c=f.closed&f.cd.gt(start)&f.cd.le(date)
  work=f.assign(active=a.astype(int),opened=o.astype(int),closed_reports=c.astype(int));g=work.groupby(['gu','industry'])[['active','opened','closed_reports']].sum()
  assert int(g.active.sum())==int(a.sum()) and int(g.opened.sum())==int(o.sum()) and int(g.closed_reports.sum())==int(c.sum())
  totals=g.active.groupby(level=0).sum()
  for (gu,industry),r in g.iterrows():
   total=int(totals.loc[gu]);rows.append({'as_of':str(date.date()),'window_start_exclusive':str(start.date()),'gu':gu,'industry':industry,'active_permits':int(r.active),'opened_365d':int(r.opened),'closed_reports_365d':int(r.closed_reports),'net_report_flow':int(r.opened-r.closed_reports),'active_share_within_covered_industries_pct':float(r.active/total*100) if total else None})
  checks.append({'as_of':str(date.date()),'active_permits':int(a.sum()),'opened':int(o.sum()),'closed_reports':int(c.sum()),'sum_check_passed':True})
 out={'reference_date':str(ref.date()),'quality':quality,'rows':rows,'checks':checks,'hashes':{'stores':snapshot_sha256(src),'script':snapshot_sha256(Path(__file__))},'limitations':['Counts are license records, not verified unique shops; uid is not unique.','15 analysis groups from 16 source industries, not all commercial activities.','Current district/industry labels reconstruct historical cohorts; boundary changes unverified.','Closed includes administrative termination, not necessarily business failure or vacancy.','Opening minus closure reports is not automatically stock change; same-day events and corrections may differ.','Latest snapshot reflects available recorded events; reporting delays and revisions possible.','Shares have a denominator limited to covered industries; no overlapping-neighborhood sums.']}
 (OUT/'district_industry_trends.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 latest=[r for r in rows if r['as_of']==str(ref.date())]
 lines=['# 구군·업종별 인허가 구성과 흐름','','자료기준일 '+str(ref.date())+'. 전체16원천업종을15그룹으로 집계. 현재구군 기준 재구성, 실제 고유점포수나 실제공실 아님. 단순 개업-폐업신고 차이를 예측확률이나 점포재고 증감으로 사용하지 않음.','','|구군|업종|기록상영업 인허가|최근365일개업|최근365일폐업신고|','|---|---|---:|---:|---:|']
 for r in latest:lines.append(f"|{r['gu']}|{r['industry']}|{r['active_permits']}|{r['opened_365d']}|{r['closed_reports_365d']}|")
 lines+=['','2021/2023/최신 세시점 전체표 및 자료한계는 JSON. 서비스에는 미반영.']
 (OUT/'district_industry_trends.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('rows',len(rows),'checks',checks)
 city={}
 for r in latest:
  x=city.setdefault(r['industry'],[0,0]);x[0]+=r['opened_365d'];x[1]+=r['closed_reports_365d']
 print('latest_industry_flows',json.dumps(city,ensure_ascii=False))
if __name__=='__main__':main()
