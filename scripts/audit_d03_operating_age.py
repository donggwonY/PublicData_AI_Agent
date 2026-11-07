"""Exploratory landmark audit: age at Jan 1, next 365-day closure report."""
import json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/d03'

def main():
    warnings.simplefilter('error', ConvergenceWarning)
    path=ROOT/'service/data/processed/stores.parquet'
    ref=pd.Timestamp(json.loads((path.parent/'meta.json').read_text(encoding='utf-8'))['reference_date'])
    f=pd.read_parquet(path); f=f[f.service.eq('일반음식점')].copy()
    bad=f.ld.isna() | (f.closed & f.cd.isna()) | (f.cd<f.ld) | (~f.closed & f.cd.notna())
    quality={'rows':len(f),'invalid_dates':int(bad.sum())}
    f=f[~bad].copy()
    def cohort(year):
        t=pd.Timestamp(year,1,1)
        assert t+pd.Timedelta(days=365)<=ref
        a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy()
        a['age_days']=(t-a.ld).dt.days
        a['age_band']=pd.cut(a.age_days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
        a['y']=(a.closed & a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
        assert a.age_days.ge(0).all()
        return a
    windows=[]
    for train_year,test_year in [(2013,2015),(2015,2017),(2018,2020)]:
        tr,te=cohort(train_year),cohort(test_year)
        assert pd.Timestamp(train_year,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test_year,1,1)
        y,yv=tr.y.to_numpy(),te.y.to_numpy()
        preds={'constant':np.full(len(te),y.mean())}
        for name,cols in [('age_only',['age_band']),('category_gu',['category','gu']),('category_gu_age',['category','gu','age_band'])]:
            x=tr[cols].astype('string').fillna('__MISSING__').astype(str)
            xv=te[cols].astype('string').fillna('__MISSING__').astype(str)
            model=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1,max_iter=2000,random_state=0))
            model.fit(x,y);preds[name]=model.predict_proba(xv)[:,1]
        groups=[]
        for band,g in te.groupby('age_band',sort=False):
            groups.append({'age_band_years_365':band,'n':len(g),'events':int(g.y.sum()),'actual_pct':float(g.y.mean()*100)})
        assert sum(g['n'] for g in groups)==len(te)
        assert sum(g['events'] for g in groups)==int(yv.sum())
        scores={name:metrics(yv,p) for name,p in preds.items()}
        windows.append({'train_date':str(pd.Timestamp(train_year,1,1).date()),'evaluation_date':str(pd.Timestamp(test_year,1,1).date()),'train_n':len(tr),'scores':scores,'age_groups':groups})
    report={'reference_date':str(ref.date()),'quality':quality,'windows':windows,'hashes':{'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__))},'limitations':['Latest-snapshot retrospective reconstruction, not historical availability proof.','Age is days since license, not verified continuous operation or owner tenure.','Same permits may occur across time windows; no ID predictors. This is existing-store forecasting, not unseen-store validation.','Exploratory reused historical years; no independent final test or 2023-2025 scoring.','Not comparable directly to opening-time first-year prediction.','No area/current status/closure date used as input; dates used only to construct cohort and outcome.']}
    (OUT/'operating_age.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# D-03 기존 영업점 운영기간 탐색','', '기준일 기록상 영업점의 다음365일 폐업·취소·말소 신고 예측. 운영기간은 인허가일부터 기준일까지 일수. 과거 상태는 최신 기록으로 재구성하며 휴업·재개업·명의변경을 확인한 실제 연속 운영기간이 아니다.','', '사전 고정: 2013→2015,2015→2017,2018→2020 각1월1일. C=1 로지스틱, 운영기간365일 기준 <1/1-3/3-5/5-10/10+ 구간. 단순평균·운영기간만·업태구군·업태구군운영기간 4후보. 현재 면적 제외. 결과 후 튜닝 없음.','', '| 평가일 | 모델 | n | 실제% | 예측% | Brier | log loss |','|---|---|---:|---:|---:|---:|---:|']
    for w in windows:
        for name,s in w['scores'].items():
            lines.append(f"| {w['evaluation_date']} | {name} | {s['n']} | {s['actual_pct']:.2f} | {s['predicted_pct']:.2f} | {s['brier']:.6f} | {s['log_loss']:.6f} |")
    lines+=['','학습 결과 관찰 종료 뒤 평가 시작 확인. 같은 인허가가 여러 기준일에 존재할 수 있어 신규점포 독립 평가가 아니다.','','가공데이터 날짜오류 검사·그룹 합계 검사 통과. 2023~2025 재평가·DB 변경·서비스 적용 없음.','', '추가 데이터: 건축HUB 건축물대장 API(15134735)는 무료·자동승인. 활용신청 확인 뒤 소량 주소 연결과 과거 시점 적합성 점검. 건물면적을 점포면적으로 대체하지 않음. 카드매출 대구 기간·비용·반출조건 미확인.']
    (OUT/'operating_age.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\n'.join(lines))
    print('AGE_GROUPS',json.dumps([{ 'date':w['evaluation_date'],'groups':w['age_groups']} for w in windows]))
if __name__=='__main__':main()
