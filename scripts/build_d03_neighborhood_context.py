"""Cross-industry spatial context; reconstructs historical permits, not actual visits."""
import json
from pathlib import Path
import pandas as pd,numpy as np
from scipy.spatial import cKDTree
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def xyz(a):
 lat,lon=np.radians(a[['lat','lon']].to_numpy()).T
 return np.column_stack([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)])
def main():
 path=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(path)
 ref=pd.Timestamp(json.loads((path.parent/'meta.json').read_text(encoding='utf-8'))['reference_date'])
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())
 valid=f.lat.between(-90,90)&f.lon.between(-180,180)&np.isfinite(f.lat)&np.isfinite(f.lon)
 quality={'raw_rows':len(f),'invalid_dates':int(bad.sum()),'missing_or_invalid_coordinates':int((~valid).sum())}
 f['source_row_id']=np.arange(len(f));f=f[~bad&valid].copy();f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 industries=sorted(f.industry.unique());radius=2*np.sin(500/6371008.8/2)
 output=[];summary=[]
 for t in [pd.Timestamp(2021,1,1),pd.Timestamp(2023,1,1),ref]:
  cutoff=t-pd.Timedelta(days=60);start=cutoff-pd.Timedelta(days=365)
  target=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy();points=xyz(target)
  result=target[['source_row_id','uid','service','building_key','industry','gu']].copy();result['as_of']=t
  active=f.ld.le(cutoff)&(f.cd.isna()|f.cd.gt(cutoff))
  opened=f.ld.gt(start)&f.ld.le(cutoff)
  closed=f.closed&f.cd.gt(start)&f.cd.le(cutoff)
  for i,name in enumerate(industries):
   own=f.industry.eq(name)
   for label,mask in [('active',active),('opened',opened),('closed',closed)]:
    src=f[own&mask]
    counts=cKDTree(xyz(src)).query_ball_point(points,radius,return_length=True,workers=2) if len(src) else np.zeros(len(target),dtype=int)
    counts=counts-target.index.isin(src.index).astype(int)
    assert np.all(counts>=0)
    result[f'{label}_{i:02d}']=counts.astype('int32')
  ac=result[[f'active_{i:02d}' for i in range(len(industries))]].to_numpy()
  total=ac.sum(axis=1);result['active_total']=total;result['industry_variety']=(ac>0).sum(axis=1)
  shares=np.divide(ac,total[:,None],out=np.zeros_like(ac,dtype=float),where=total[:,None]>0)
  result['concentration_hhi']=(shares**2).sum(axis=1);result.loc[total==0,'concentration_hhi']=np.nan
  own_idx=target.industry.map({n:i for i,n in enumerate(industries)}).to_numpy()
  result['same_industry_active']=ac[np.arange(len(ac)),own_idx]
  result['opened_total']=result[[f'opened_{i:02d}' for i in range(len(industries))]].sum(axis=1)
  result['closed_total']=result[[f'closed_{i:02d}' for i in range(len(industries))]].sum(axis=1)
  result['net_permit_flow']=result.opened_total-result.closed_total
  assert result.source_row_id.is_unique
  groups=[]
  for name,g in result.groupby('industry'):
   groups.append({'industry':name,'n':len(g),'median_nearby_active':float(g.active_total.median()),'median_same_industry':float(g.same_industry_active.median()),'median_industry_variety':float(g.industry_variety.median()),'median_recent_openings':float(g.opened_total.median()),'median_recent_closures':float(g.closed_total.median())})
  summary.append({'as_of':str(t.date()),'feature_cutoff':str(cutoff.date()),'n':len(result),'no_nearby_active':int((total==0).sum()),'groups':groups})
  output.append(result);print('built',str(t.date()),len(result),flush=True)
 data=pd.concat(output,ignore_index=True);assert not data.duplicated(['source_row_id','as_of']).any()
 dest=ROOT/'data/raw/d03/neighborhood_context.parquet';dest.parent.mkdir(parents=True,exist_ok=True);data.to_parquet(dest,index=False)
 report={'quality':quality,'radius_m':500,'lag_days':60,'event_lookback_days':365,'industry_columns':{f'{i:02d}':n for i,n in enumerate(industries)},'dates':summary,'rows':len(data),'local_dataset':'data/raw/d03/neighborhood_context.parquet','hashes':{'stores':snapshot_sha256(path),'features':snapshot_sha256(dest),'script':snapshot_sha256(Path(__file__))},'limitations':['Latest coordinates and current snapshot reconstruct past permits; relocation and reporting availability unverified.','Counts represent permits, not verified independent storefronts; same-address permits retained.','Opening counts include entrants subsequently closed; flows are not automatically vacancy or stock change.','500m straight-line radius, self permit excluded, neighboring permits may share building.','Only 16 source industries/15 groups, not all commercial activities or proposed 42 industries.','60-day lag is a conservative assumption, not verified reporting delay.','Overlapping neighborhoods cannot be summed to city totals.','Current-date context has no completed future365-day outcome. No model fit or service changes.']}
 (OUT/'neighborhood_context.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 (OUT/'neighborhood_context.md').write_text('# 전체 업종 주변 상권 정보\n\n반경500m, 자기 인허가 제외. 기준일60일 전까지 정보로 주변15그룹별 영업 인허가 수·직전365일 신규/폐업 신고수를 생성. 업종다양성·집중도·동종업종수·전체신규/폐업 흐름 포함. 2021/2023 및 자료기준일 스냅샷.\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n\n한계: 최신 좌표로 과거를 재구성, 이전·명의변경 미확인. 인허가 건수를 실제 점포수로 단정하지 않음. 주소 중복은 보존. 전 업종 포괄 아님. 개업-폐업은 공실 또는 점포재고 순변화가 아님. 상세 설명·해시는 JSON. 원본 특성파일은 로컬 data/raw/d03에 보관, 아직 모델학습/DB/서비스 반영 없음.\n',encoding='utf-8')
 print('saved_rows',len(data),'columns',len(data.columns),flush=True)
if __name__=='__main__':main()
