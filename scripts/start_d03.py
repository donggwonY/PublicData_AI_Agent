"""D-03 baseline reproduction and one-year outcome feasibility, no model fitting."""
import ast,json,sys,importlib.util,platform
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import numpy as np
import pyarrow
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]

def main():
    service=ROOT/'service';data=service/'data/processed';out=ROOT/'docs/d03';out.mkdir(exist_ok=True)
    meta=json.loads((data/'meta.json').read_text(encoding='utf-8'))
    ref=pd.Timestamp(meta['reference_date'])
    st=pd.read_parquet(data/'stores.parquet')
    st['analysis_group']=st.service.replace({'의원':'의원·병원','병원':'의원·병원'})
    assert st.service.nunique()==16 and st.analysis_group.nunique()==15
    saved=pd.read_parquet(data/'survival.parquet')
    spec=importlib.util.spec_from_file_location('baseline_survival',service/'core/survival.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    cfg={}
    for n in ast.parse((service/'config.py').read_text(encoding='utf-8')).body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'SURVIVAL_START_YEAR','MIN_GROUP_N'} for t in n.targets):
            exec(compile(ast.Module(body=[n],type_ignores=[]),'config.py','exec'),{},cfg)
    ns={'pd':pd,'json':json,'C':SimpleNamespace(**cfg),'summarize':mod.summarize}
    fn=next(n for n in ast.parse((service/'pipeline/build.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='build_survival')
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'build.py','exec'),ns)
    rebuilt,_=ns['build_survival'](st)
    pd.testing.assert_frame_equal(rebuilt.reset_index(drop=True),saved.reset_index(drop=True),check_dtype=False)
    expected=(st.cd.where(st.closed,ref)-st.ld).dt.days
    assert expected.eq(st.dur_days).all()
    eligible=st.ld.ge(pd.Timestamp('2010-01-01')) & st.ld.le(ref-pd.Timedelta(days=365))
    f=st[eligible].copy()
    f['event365']=f.closed & (f.cd-f.ld).dt.days.le(365)
    f['open_year']=f.ld.dt.year
    assert (ref-f.ld).dt.days.ge(365).all()
    tables={}
    for name,keys in [('service',['service']),('analysis_group',['analysis_group']),('analysis_group_year',['analysis_group','open_year']),('open_year',['open_year']),('service_year',['service','open_year'])]:
        g=f.groupby(keys,dropna=False).agg(n=('uid','size'),events365=('event365','sum'))
        g['observed_event_pct']=(100*g.events365/g.n).round(2)
        g['small_n']=g.n.lt(30)
        assert int(g.n.sum())==len(f)
        tables[name]=json.loads(g.reset_index().to_json(orient='records',force_ascii=False))
    medical=f[f.service.isin(['의원','병원'])]
    grouped=next(row for row in tables['analysis_group'] if row['analysis_group']=='의원·병원')
    assert grouped['n']==len(medical) and grouped['events365']==int(medical.event365.sum())
    result={'analysis_groups':int(st.analysis_group.nunique()),'group_mapping':{'의원':'의원·병원','병원':'의원·병원'},'reference_date':str(ref.date()),'built_at':meta['built_at'],'records':len(st),'services':int(st.service.nunique()),'survival_rows_reproduced':len(saved),'eligible365':len(f),'events365':int(f.event365.sum()),'excluded_recent_since2010':int((st.ld.ge(pd.Timestamp('2010-01-01'))&~eligible).sum()),'tables':tables,
            'versions':{'python':platform.python_version(),'pandas':pd.__version__,'numpy':np.__version__,'pyarrow':pyarrow.__version__},
            'hashes':{str(p.relative_to(ROOT)):snapshot_sha256(p) for p in [data/'meta.json',data/'stores.parquet',data/'survival.parquet',service/'core/survival.py',service/'pipeline/build.py',service/'config.py']}}
    (out/'baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-03 시작: 생존 기준선과 1년 결과 가용성','',f'기준일 {ref.date()}, 인허가 {len(st):,}건, 원천 업종명 {st.service.nunique()}개 / 분석 그룹 {st.analysis_group.nunique()}개. 기존 생존 요약 {len(saved)}행 전체 재현 일치. 종료일 유도 기간도 저장 dur_days와 일치.','',
           '## 추천 분석 질문','','개업 당시 확보 가능한 정보로 개업 후 365일 이내 폐업·취소·말소 신고 여부를 예측할 수 있는가? 아직 최종 업종·모델·분할은 확정하지 않은 추천 초안이다. 수익성이나 실제 사업 실패 예측과 구분한다.','',
           '## 표본 정의','','2010년 이후 개업했고 기준일 이전에 365일 추적 기회가 확보된 인허가만 고정기간 결과 비교에 사용한다. 최근 개업 중 조기 폐업한 행만 골라 포함하지 않는다. 사건은 closed=true 및 폐업일까지 365일 이하(경계 포함). 영업중은 KM에서 중도절단이며, 충분히 추적 가능한 365일 이진 결과에서는 사건 없음이다.',
           f'대상 {len(f):,}건, 365일 사건 {int(f.event365.sum()):,}건. 최근 개업으로 제외 {result["excluded_recent_since2010"]:,}건. 365일과 달력상 12개월은 윤년에 다를 수 있어 이번 초안은 365일로 고정한다.','',
           '```text',pd.DataFrame(tables['analysis_group']).to_string(index=False),'```','',
           '## 해석·다음 단계','','- 이 비율은 가공본에 남은 인허가의 관측 결과이며 원천 누락이나 선택 편향이 없음을 보증하지 않는다.',
           '- D-02는 7개 업종의 이전 스냅샷 분석이다. 새 확장 업종 결과와 혼합하지 않는다.',
           '- 다음은 대상 업종과 연도별 학습/검증/시험 분할을 정하고, 미래 정보가 들어가지 않는 변수 목록을 작성한다. 현재 표에는 시험 기간 후보 결과도 포함되어 있으므로 모델 선택에는 별도로 고정한 검증기간만 사용해야 한다.',
           '- 개업 시점에 알 수 없는 폐업일·영업기간·현재 영업상태·전체기간 자리 요약·최신 보조자료를 입력에서 제외한다.',
           '- uid/주소의 학습·시험 중복과 과거 자료의 당시 이용 가능성도 확인한다. 연도순 분할만으로 누출 문제가 해결되는 것은 아니다.',
           '- 모델 학습·서비스 배포·운영 DB 조회는 하지 않았다. 로컬 Parquet 기준 검증이다.',
           '- 실행 패키지 버전은 baseline.json에 기록했다. 기존 로컬 분석 패키지를 사용한 가상환경이며 배포 고정 버전과 완전히 동일한 환경 검증은 아니다.',
           '', '재현: 저장소 루트에서 Python 3.12 분석 가상환경으로 `python scripts/start_d03.py`. 입력·코드 해시는 baseline.json에 기록한다.','']
    lines += ['', '## 업종 묶음과 설명 원칙', '', '2026-10-17 사용자 결정: 원천 service의 의원·병원 구분을 유지하고 분석용 analysis_group에서만 의원·병원으로 묶는다. 나머지 업종명은 그대로 유지한다. 따라서 원천 업종명 16개, 분석 대상 15개 그룹이다. 예정에 없던 업종이 추가된 것이 아니라 집계 단위의 차이다.', '', '공유할 설명: 원본 데이터에서는 의원과 병원이 나뉘어 있어 16개지만, 팀에서 정한 기준에 따라 분석할 때는 의원·병원을 묶어 15개 그룹으로 봅니다. 두 업종의 세부 결과도 따로 남겨 차이를 확인할 수 있게 했습니다.', '', '아래는 365일 추적 가능 의료 업종의 원천 구분이다. 합산 비율은 건수로 다시 계산하며 두 비율을 단순 평균하지 않는다. 원천별 표와 연도별 표도 baseline.json에 보존한다. 추후 의료 업종 생존·예측 분석 시 개별 결과와 통합 결과를 함께 비교한다.', '', '```text', pd.DataFrame([row for row in tables['service'] if row['service'] in ['의원','병원']]).to_string(index=False), '```', '', '## 진행 상태와 범위 제안', '', 'D-03 진행 중. 첫 모델은 일반음식점(365일 추적 가능 42,342건·사건 4,755건)으로 좁히는 것을 추천한다. 아직 확정한 선택은 아니다. 다음은 시간 분할·변수 목록·누출 점검과 기준선 비교다. 완료 기준은 문제 정의서, 기준선/후보 비교, 확률 보정·지역/업종 오류 분석 및 서비스 채택/보류 근거다.', '']
    (out/'README.md').write_text('\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines())+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'tables','hashes'}},ensure_ascii=False))
if __name__=='__main__':main()
