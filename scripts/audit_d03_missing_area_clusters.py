"""Frozen full-coverage baseline audit; no 2023-2025 scoring."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
from fit_d03 import ROOT,metrics,verify_snapshot_hash,snapshot_sha256,Pipeline,OneHotEncoder,LogisticRegression
from fit_d03_expanded import fit
sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area
def main():
 out=ROOT/'docs/d03';old=json.loads((out/'validation.json').read_text(encoding='utf-8'));area_ref=json.loads((out/'area_complete.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 verify_snapshot_hash(sp,old['hashes']['stores']);verify_snapshot_hash(rp,area_ref['hashes']['raw']);verify_snapshot_hash(ROOT/'service/pipeline/numeric.py',area_ref['hashes']['parser'])
 st=pd.read_parquet(sp);f=st[st.service.eq('일반음식점')&st.ld.dt.year.between(2010,2021)].copy().reset_index(drop=True)
 assert not (f.cd.notna()&f.cd.lt(f.ld)).any()
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적','최종수정시점','데이터갱신시점','영업상태명','상세영업상태명','폐업일자']);r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 key=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 raw=key.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw);area=f.area_m2.copy();recover=area.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna();area.loc[recover]=parsed[recover].astype(float)
 coord=f.lat.between(-90,90)&f.lon.between(-180,180);valid=np.isfinite(area)&area.gt(0)
 f['coverage']=np.where(~coord,'coordinate_excluded',np.where(~valid,'area_excluded','included'))
 f['event']=(f.closed&(f.cd-f.ld).dt.days.between(0,365)).astype(int)
 f['duration']=(f.cd-f.ld).dt.days
 f['raw_area_kind']=np.where(raw.isna()|raw.fillna('').str.strip().eq(''),'blank',np.where(parsed.le(0).fillna(False),'nonpositive',np.where(parsed.gt(0).fillna(False),'positive','unparsed')))
 rr=r.set_index('key')
 for col in ['최종수정시점','데이터갱신시점','영업상태명','상세영업상태명','폐업일자']:f[col]=key.map(rr[col])
 f['close_month']=f.cd.dt.strftime('%Y-%m').fillna('__MISSING__')
 f['duration_band']=pd.cut(f.duration,[-1,0,7,30,90,180,365,float('inf')],labels=['0','1-7','8-30','31-90','91-180','181-365','366+']).astype('string').fillna('no_date')
 ref=json.loads((out/'missing_area_patterns.json').read_text(encoding='utf-8'));windows=[]
 f['building']=f.building_key.astype('string').fillna('').str.strip()
 f['opened']=f.ld.dt.strftime('%Y-%m-%d');f['closed_day']=f.cd.dt.strftime('%Y-%m-%d')
 for start,stop in [(2015,2016),(2017,2018),(2020,2021)]:
  va=f[f.ld.dt.year.between(start,stop)];g=va[va.coverage.eq('area_excluded')];ev=g[g.event.eq(1)]
  expected=next(w for w in ref['windows'] if w['window']==f'{start}-{stop}')
  assert len(g)==expected['n'] and len(ev)==expected['events']
  tables={};summary={}
  for label,cols in [('same_dates',['opened','closed_day']),('same_building',['building']),('same_building_dates',['building','opened','closed_day'])]:
   eligible=ev[ev.building.ne('')] if 'building' in cols else ev
   table=eligible.groupby(cols,dropna=False).agg(n=('event','size'),short_n=('duration',lambda x:int(x.between(0,30).sum())),districts=('gu',lambda x:', '.join(sorted(set(x.dropna().astype(str)))))).reset_index()
   assert table.n.sum()==len(eligible)
   table=table.sort_values('n',ascending=False)
   summary[label]={'eligible_n':len(eligible),'clustered_rows':int(table.loc[table.n.ge(2),'n'].sum()),'clusters':int(table.n.ge(2).sum()),'largest':int(table.n.max()) if len(table) else 0}
   tables[label]=json.loads(table.to_json(orient='records',force_ascii=False))
  windows.append({'window':expected['window'],'area_excluded_n':len(g),'events':len(ev),'missing_building_events':int(ev.building.eq('').sum()),'summary':summary,'tables':tables})
 report={'scope':'descriptive grouping of missing-area 365-day report events; building is not shop unit; not evidence of temporary permit','windows':windows,'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__)),'prior':snapshot_sha256(out/'missing_area_patterns.json')}}
 (out/'missing_area_clusters.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 면적 제외 신고의 건물·날짜 집중','','기존 365일 이내 신고 사건만 대상으로 현재 building_key와 개업/폐업 신고일을 묶었다. 같은 건물이 같은 점포라는 뜻은 아니다. 날짜는 실제 영업 시작/종료를 보장하지 않는다. 빈 건물키는 묶지 않았다.','','| 기간 | 신고 사건 | 같은 건물·같은 두 날짜에 2건 이상 속한 사건 | 최대 집단 |','| --- | ---: | ---: | ---: |']
 for w in windows:
  q=w['summary']['same_building_dates'];lines.append(f"| {w['window']} | {w['events']} | {q['clustered_rows']} | {q['largest']} |")
  print(json.dumps({'window':w['window'],'events':w['events'],'summary':w['summary'],'top':w['tables']['same_building_dates'][:3]},ensure_ascii=False))
 lines+=['','## 상위 집단','', '| 기간 | 건물키 | 개업일 | 폐업 신고일 | 건수 |','| --- | --- | --- | --- | ---: |']
 for w in windows:
  for q in w['tables']['same_building_dates'][:5]:lines.append(f"| {w['window']} | {q['building']} | {q['opened']} | {q['closed_day']} | {q['n']} |")
 lines+=['','원본 해시·키 유일성·기존 집단/사건 수·모든 집계 합계 검증 통과. 동일 날짜/장소 집중만으로 행사·한시허가 또는 행정 오류를 확정할 수 없다. 결과를 근거로 행 삭제·재학습·서비스 적용하지 않았다. 개별 허가 자료나 당시 행사 기록과의 독립 대조가 필요하다.']
 (out/'missing_area_clusters.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__':main()
