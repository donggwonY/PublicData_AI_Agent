"""Monthly transit follow-up; fixed historical validation, no final test reuse."""
import argparse, json, calendar, platform
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from fit_d03 import ROOT, metrics, snapshot_sha256, verify_snapshot_hash
from fit_d03_expanded import make_features, target, fit, CATS, NUMS

ACCESS=['station_matched','distance_km']
TRAFFIC=['board_level','alight_level','board_change','alight_change']
WINDOWS=[(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]

def read_monthly(path):
    d=pd.read_csv(path,encoding='cp949')
    ix=pd.PeriodIndex(pd.to_datetime(dict(year=d.iloc[:,0].astype(int),month=d.iloc[:,1].astype(int),day=1)),freq='M')
    assert ix.is_unique and ix.equals(pd.period_range(ix.min(),ix.max(),freq='M'))
    a=d.iloc[:,2:].apply(pd.to_numeric)
    assert a.notna().all().all() and (a>=0).all().all() and a.columns.is_unique
    a.index=ix
    return a

def distance(lat,lon,p):
    x=np.radians(lat);y=np.radians(p['latitude']);dl=np.radians(lon-p['longitude'])
    return 6371000*2*np.arcsin(np.sqrt(np.clip(np.sin((x-y)/2)**2+np.cos(x)*np.cos(y)*np.sin(dl/2)**2,0,1)))

def rates(frame, month, names):
    periods=pd.period_range(month-2,month,freq='M')
    a=frame.reindex(periods)[names].to_numpy(float)
    ok=(np.isfinite(a)&(a>0)).all(axis=0)
    days=np.array([calendar.monthrange(p.year,p.month)[1] for p in periods])
    result=a.sum(axis=0)/days.sum()
    return np.where(ok,result,np.nan)

def features(f,b,a,groups):
    names=[g['csv_name'] for g in groups]
    dist=np.column_stack([np.min(np.column_stack([distance(f.lat.to_numpy(),f.lon.to_numpy(),p) for p in g['points']]),axis=1) for g in groups])
    months=f.ld.dt.to_period('M')-2
    out=np.zeros((len(f),6));out[:,1]=1;out[:,2:]=np.nan
    selected=np.full(len(f),'',dtype=object)
    for month in sorted(months.unique()):
        ids=np.flatnonzero(months.eq(month).to_numpy())
        eligible=(b.loc[month,names].to_numpy()>0)&(a.loc[month,names].to_numpy()>0)
        dd=np.where(eligible[None,:],dist[ids],np.inf)
        best=dd.argmin(axis=1);valid=dd[np.arange(len(ids)),best]<=1000
        hit=ids[valid];choice=best[valid]
        out[hit,0]=1;out[hit,1]=dd[np.flatnonzero(valid),choice]/1000
        selected[hit]=np.array(names)[choice]
        rb,ra=rates(b,month,names),rates(a,month,names)
        pb,pa=rates(b,month-12,names),rates(a,month-12,names)
        vals=np.column_stack([np.log1p(rb),np.log1p(ra),np.log1p(rb)-np.log1p(pb),np.log1p(ra)-np.log1p(pa)])
        out[hit,2:]=vals[choice]
    return out,selected

def model(kind,extra):
    nums=NUMS+(ACCESS if extra>=1 else [])+(TRAFFIC if extra>=2 else [])
    numeric=Pipeline([('impute',SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)),('scale',StandardScaler())])
    tf=ColumnTransformer([('cats',OneHotEncoder(handle_unknown='ignore',sparse_output=False),CATS),('nums',numeric,nums)])
    est=(RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=2) if kind=='forest' else LogisticRegression(C=1,max_iter=2000,random_state=0))
    return Pipeline([('features',tf),('model',est)])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--raw-dir',type=Path,required=True);args=parser.parse_args()
    out=ROOT/'docs/d03';old=json.loads((out/'expanded_experiments.json').read_text(encoding='utf-8'))
    verify_snapshot_hash(ROOT/'service/data/processed/stores.parquet',old['hashes']['stores'])
    bp=args.raw_dir/'대구교통공사_월별승차인원_20260731.csv';ap=args.raw_dir/'대구교통공사_월별하차인원_20260731.csv'
    b,a=read_monthly(bp),read_monthly(ap);assert b.columns.equals(a.columns)
    lp=ROOT/'docs/a01/station_locations.json';loc=json.loads(lp.read_text(encoding='utf-8'))
    groups=[]
    for g in loc['station_exit_groups']:
        name={'어린이회관':'어린이세상'}.get(g['traffic_station'],g['traffic_station'])
        if g['traffic_match'] and not g['review_cluster'] and name in b.columns:
            assert g['points'] and all(33<p['latitude']<39 and 124<p['longitude']<132 for p in g['points'])
            groups.append(dict(g,csv_name=name))
    assert len({g['csv_name'] for g in groups})==len(groups)
    f=make_features(pd.read_parquet(ROOT/'service/data/processed/stores.parquet')).reset_index(drop=True)
    values,selected=features(f,b,a,groups);f[ACCESS+TRAFFIC]=values
    # Changing every transit value after each sample's cutoff must not change its features.
    for idx in [0,len(f)//2,len(f)-1]:
        one=f.iloc[[idx]].copy();cut=one.ld.iloc[0].to_period('M')-2
        bb=b.copy();aa=a.copy();bb.loc[bb.index>cut]=123456789;aa.loc[aa.index>cut]=987654321
        test,_=features(one,bb,aa,groups)
        assert np.allclose(test,values[[idx]],equal_nan=True)
    # Synthetic future station must not be selected, and partial histories must stay missing.
    toy=b.copy();toy.iloc[:,:]=0
    assert np.isnan(rates(toy,toy.index[-1],list(toy.columns))).all()
    zero,_=features(f.iloc[[0]],toy,toy,groups);assert zero[0,0]==0 and np.isnan(zero[0,2:]).all()
    windows=[];sub=[]
    print('Features ready',len(f),'matched',int(f.station_matched.sum()),flush=True)
    for end,start,stop in WINDOWS:
        tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)]
        assert not set(tr.index)&set(va.index)
        assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
        y,yv=target(tr),target(va);pred={'constant':np.full(len(va),y.mean())}
        for kind in ['logistic','forest']:
            for extra,label in [(0,'context'),(1,'access'),(2,'traffic')]:
                name=kind+'_'+label;m=fit(model(kind,extra),tr,y);pred[name]=m.predict_proba(va)[:,1]
                print(start,name,flush=True)
        scores={}
        for name,p in pred.items():
            assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all();scores[name]=metrics(yv,p)
            for value in [0,1]:
                mask=va.station_matched.eq(value).to_numpy()
                if mask.any():sub.append({'window':f'{start}-{stop}','model':name,'matched':value,**metrics(yv[mask],p[mask])})
        prior=next(w for w in old['windows'] if w['window']==f'{start}-{stop}')
        for new,prev in [('constant','constant'),('logistic_context','context'),('forest_context','forest_context')]:
            for key in ['n','events','brier','log_loss']:
                assert np.isclose(scores[new][key],prior['scores'][prev][key],atol=1e-5,rtol=1e-4),(new,key)
        windows.append({'window':f'{start}-{stop}','train_n':len(tr),'matched_n':int(va.station_matched.sum()),'scores':scores})
    passed=[kind for kind in ['logistic','forest'] if all(w['scores'][kind+'_traffic'][metric]<w['scores'][baseline][metric] for w in windows for metric in ['brier','log_loss'] for baseline in ['constant',kind+'_access'])]
    result={'scope':'retrospective exploration; 2023-2024 not rescored','windows':windows,'subgroups':sub,'passed':passed,
        'coverage':{'station_groups':len(groups),'unmatched_stations':sorted(set(b.columns)-{g['csv_name'] for g in groups}),'target_n':len(f),'matched_n':int(f.station_matched.sum()),'missing_features':{c:int(f[c].isna().sum()) for c in TRAFFIC},'boarding_months':len(b),'alighting_months':len(a)},
        'hashes':{'boarding':snapshot_sha256(bp),'alighting':snapshot_sha256(ap),'locations':snapshot_sha256(lp),'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'transit_experiment_plan.md'),'stores':old['hashes']['stores'],'feature_helper':snapshot_sha256(ROOT/'scripts/fit_d03_expanded.py'),'spatial_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'metrics_helper':snapshot_sha256(ROOT/'scripts/fit_d03.py')},
        'versions':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,'sklearn':sklearn.__version__}}
    (out/'transit_experiment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-03 月別 지하철 추가 실험'.replace('月別','월별'),'','개업 월 2개월 전까지의 지하철 이용량을 기존 입력에 추가한 후속 탐색. 2023~2024 시험 재사용 없음.','','| 기간 | 모델 | 표본 | 실제% | 예측% | Brier | log loss | AUC |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for w in windows:
        for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
    lines+=['','context=기존 주변 상권, access=역 연결·거리 추가, traffic=과거 월별 이용량·전년 대비 변화 추가. Brier/log loss는 작을수록 좋다.','',f"세 기간 모두 상수 및 같은 알고리즘 접근성 모델보다 두 확률 오차 개선: {passed or '없음'}.",'',f"좌표 연결 가능한 역·호선 {len(groups)}개, 미연결 {result['coverage']['unmatched_stations']}. 전체 {len(f):,}건 중 당시 이용 기록이 있는 출구1km 이내 {int(f.station_matched.sum()):,}건.",'','## 검증과 한계','','월 연속/중복·수치·좌표 키 검사, 미래 월 값을 바꿔도 입력 불변인3개 표본, 0기록/부분 이력 결측 처리, 시간 분리·365일 간격·기존 모델 지표 재현·수렴·확률 범위 검사 통과. 세 기간7후보21평가와 역 연결 여부별 결과를 JSON에 기록.','', '현재 출구 위치의 과거 일치와 실제 월별 공개일은 미확인이다. 양수 기록 조건은 개통일 검증이 아니며 일시 중단 역도 제외될 수 있다. 좌표 미연결·1km 밖을 수요0으로 해석하지 않는다. 가장 가까운 역·호선만 사용하므로 주변 전체 교통량이 아니다. 역 이용객은 가게 방문객/매출이 아니며 개업 전 과거의 간접 수요 지표다. 이미 반복 활용한 검증기간이므로 개선되어도 독립 성능 입증이나 인과 효과가 아니다.','','운영 서비스·DB 변경 없음. 기존 공유 DB 연결 미설정 상태에서 로컬 분석만 수행. 원본 파일 보존. [사전 계획](transit_experiment_plan.md), [전체 결과](transit_experiment.json).','','재현: 기존 D-03 분석 환경에서 `python scripts/fit_d03_transit.py --raw-dir "월별 CSV가 있는 폴더"`.']
    (out/'transit_experiment.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'coverage':result['coverage'],'passed':passed,'windows':windows},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
