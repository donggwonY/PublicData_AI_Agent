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
 ref=json.loads((out/'full_coverage.json').read_text(encoding='utf-8'));windows=[]
 for start,stop in [(2015,2016),(2017,2018),(2020,2021)]:
  va=f[f.ld.dt.year.between(start,stop)];g=va[va.coverage.eq('area_excluded')]
  oldw=next(w for w in ref['windows'] if w['window']==f'{start}-{stop}')
  expected=next(q for q in oldw['groups'] if q['model']=='constant' and q['field']=='coverage' and q['group']=='area_excluded')
  assert len(g)==expected['n'] and g.event.sum()==expected['events']
  tables={}
  for field in ['gu','category','raw_area_kind','duration_band','close_month','영업상태명','상세영업상태명']:
   table=g.groupby(g[field].fillna('__MISSING__')).agg(n=('event','size'),events=('event','sum')).reset_index().rename(columns={field:'group'})
   assert table.n.sum()==len(g) and table.events.sum()==g.event.sum()
   tables[field]=json.loads(table.sort_values(['events','n'],ascending=False).to_json(orient='records',force_ascii=False))
  windows.append({'window':oldw['window'],'n':len(g),'events':int(g.event.sum()),'tables':tables})
 result={'scope':'historical missing-area descriptive audit; no predictions or causal identification','windows':windows,'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__)),'baseline':snapshot_sha256(out/'full_coverage.json')}}
 (out/'missing_area_patterns.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 과거 면적 제외 집단 원본 패턴','','기존 세 평가기간의 면적 제외 집단만 기술적으로 집계했다. 신고 후 누락이 생겼는지, 누락이 폐업과 인과관계가 있는지는 확인할 수 없다. 현재 상태·신고일·기간은 원인 조사용 사후 항목이며 예측 입력이 아니다.']
 for w in windows:
  lines+=['',f"## {w['window']}: {w['n']}건 / 365일 이내 신고 {w['events']}건"]
  for field in ['gu','category','raw_area_kind','duration_band','close_month','영업상태명']:
   lines+=['',f'### {field}', '', '| 그룹 | 건수 | 365일 이내 신고 |','| --- | ---: | ---: |']
   for q in w['tables'][field][:6]:lines.append(f"| {q['group']} | {q['n']} | {q['events']} |")
 lines+=['','집계 상위6개만 표에 표시; 전체 분포는 JSON에 보존. 원본 해시·키 유일성·기존 제외/사건 수·집계 합계 검증 통과. 행 삭제·누락 지표 입력·재학습 없음. 날짜는 폐업 신고 날짜이며 실제 폐점일을 보장하지 않는다.']
 (out/'missing_area_patterns.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 for w in windows:print(json.dumps({'window':w['window'],'n':w['n'],'events':w['events'],'top':{k:v[:3] for k,v in w['tables'].items()}},ensure_ascii=False))
if __name__=='__main__':main()
