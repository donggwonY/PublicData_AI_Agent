"""Audit excluded 2025 rows; no prediction fitting or rescoring."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area
def main():
 out=ROOT/'docs/d03';prior=json.loads((out/'area_complete.json').read_text(encoding='utf-8'));evaluation=json.loads((out/'area_2025.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 for name,p in [('stores',sp),('raw',rp),('parser',ROOT/'service/pipeline/numeric.py')]:verify_snapshot_hash(p,prior['hashes'][name])
 s=pd.read_parquet(sp);f=s[s.service.eq('일반음식점')&s.ld.between('2025-01-01','2025-09-30')].copy()
 ref=pd.Timestamp(json.loads((ROOT/'service/data/processed/meta.json').read_text(encoding='utf-8'))['reference_date']);assert (f.ld+pd.Timedelta(days=365)).le(ref).all()
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적']);r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 keys=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 raw=keys.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw);area=f.area_m2.copy();recover=area.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna();area.loc[recover]=parsed[recover].astype(float)
 coord=f.lat.between(-90,90)&f.lon.between(-180,180);valid=np.isfinite(area)&area.gt(0)
 f['coverage']=np.where(~coord,'coordinate_excluded',np.where(~valid,'area_excluded','included'))
 f['event']=(f.closed&(f.cd-f.ld).dt.days.between(0,365)).astype(int)
 counts=f.coverage.value_counts();assert len(f)==evaluation['test_original_n']==1940
 assert counts['coordinate_excluded']==evaluation['test_coord_excluded']==39
 assert counts['area_excluded']==evaluation['test_area_excluded']==293
 assert counts['included']==evaluation['scores']['forest_area']['n']==1608
 assert int(f.loc[f.coverage.eq('included'),'event'].sum())==evaluation['scores']['forest_area']['events']
 groups=[]
 for field in ['gu','category']:
  for name,g in f.groupby(f[field].astype('string').fillna('__MISSING__')):
   kept=g.coverage.eq('included');groups.append({'field':field,'group':str(name),'n':len(g),'included':int(kept.sum()),'coordinate_excluded':int(g.coverage.eq('coordinate_excluded').sum()),'area_excluded':int(g.coverage.eq('area_excluded').sum()),'excluded_pct':float((~kept).mean()*100),'events_included':int(g.loc[kept,'event'].sum()),'events_excluded':int(g.loc[~kept,'event'].sum())})
  subset=[g for g in groups if g['field']==field];assert sum(g['n'] for g in subset)==len(f);assert sum(g['included'] for g in subset)==1608;assert sum(g['events_included']+g['events_excluded'] for g in subset)==int(f.event.sum())
 totals=[{'group':str(name),'n':len(g),'events':int(g.event.sum()),'event_pct':float(g.event.mean()*100)} for name,g in f.groupby('coverage')]
 result={'scope':'2025 sample coverage description, not model evaluation','reference_date':str(ref.date()),'original_n':len(f),'excluded_n':332,'totals':totals,'groups':groups,'overlapping_coordinate_and_area_invalid':int((~coord&~valid).sum()),'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py'),'script':snapshot_sha256(Path(__file__))}}
 (out/'excluded_coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 面積・좌표 제외 표본 점검'.replace('面積・','면적·'),'','2025년1~9월 일반음식점 전체1,940건 중332건(17.11%)이 기존 평가에서 제외됐다. 좌표를 먼저 제외한 뒤 면적을 확인한 기존 순서를 재현했다. 중복 제외 없음. 모델 재학습·예측 재채점 없음.','','| 구군 | 전체 | 포함 | 좌표 제외 | 면적 제외 | 제외율% |','| --- | ---: | ---: | ---: | ---: | ---: |']
 for g in groups:
  if g['field']=='gu':lines.append(f"| {g['group']} | {g['n']} | {g['included']} | {g['coordinate_excluded']} | {g['area_excluded']} | {g['excluded_pct']:.2f} |")
 lines+=['','## 업태별 제외 건수 상위','','| 업태 | 전체 | 제외 | 제외율% |','| --- | ---: | ---: | ---: |']
 for g in sorted([g for g in groups if g['field']=='category'],key=lambda g:g['n']-g['included'],reverse=True)[:8]:lines.append(f"| {g['group']} | {g['n']} | {g['n']-g['included']} | {g['excluded_pct']:.2f} |")
 lines+=['','제외 가게의 신고 건수는 표본 구성 설명용이다. 이를 보고 제외/대체 기준을 바꾸거나 성능 개선을 주장하지 않는다. 좌표/면적 결측 원인, 당시값 여부는 미확인. 포함표본의 정확도를 제외표본이나 일반음식점 전체에 일반화하지 않는다. 원본키·입력해시·기존 제외수·사건수·구군/업태 합계 검증 통과. [전체결과](excluded_coverage.json).']
 (out/'excluded_coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'totals':totals,'districts':[g for g in groups if g['field']=='gu'],'top_categories':sorted([g for g in groups if g['field']=='category'],key=lambda g:g['n']-g['included'],reverse=True)[:3]},ensure_ascii=False))
if __name__=='__main__':main()
