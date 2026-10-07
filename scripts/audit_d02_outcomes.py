"""Read-only audit of closure, vacancy and survival definitions."""
import ast
import hashlib
import importlib.util
import json
from types import SimpleNamespace
import pandas as pd
from audit_d02_units import ROOT, DEMO


def main():
    data=DEMO/'data/processed'
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    for name, value in manifest['sha256'].items():
        assert hashlib.sha256((data/name).read_bytes()).hexdigest()==value, name
    st=pd.read_parquet(data/'stores.parquet')
    u=pd.read_parquet(data/'units.parquet')
    ref=pd.Timestamp(manifest['reference_date'])
    spec=importlib.util.spec_from_file_location('demo_survival',DEMO/'core/survival.py')
    survival=importlib.util.module_from_spec(spec);spec.loader.exec_module(survival)
    config_tree=ast.parse((DEMO/'config.py').read_text(encoding='utf-8'))
    keys={'SURVIVAL_START_YEAR','MIN_GROUP_N','VACANCY_MIN_DAYS','VACANCY_MAX_DAYS'}
    cfg={}
    for node in config_tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in keys for t in node.targets):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'config.py','exec'),{},cfg)
    ns={'pd':pd,'json':json,'C':SimpleNamespace(**cfg),'summarize':survival.summarize}
    tree=ast.parse((DEMO/'pipeline/build.py').read_text(encoding='utf-8'))
    for name in ['build_survival','build_vacancy_area']:
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'build.py','exec'),ns)
    rebuilt,decades=ns['build_survival'](st)
    saved=pd.read_parquet(data/'survival.parquet')
    pd.testing.assert_frame_equal(rebuilt.reset_index(drop=True),saved.reset_index(drop=True),check_dtype=False)
    vac=ns['build_vacancy_area'](u)
    pd.testing.assert_frame_equal(vac.reset_index(drop=True),pd.read_parquet(data/'vacancy_area.parquet').reset_index(drop=True),check_dtype=False)
    expected_end=st.cd.where(st.closed,ref)
    # This snapshot omits end; validate its implied duration instead.
    assert ((expected_end-st.ld).dt.days.clip(lower=0)==st.dur_days).all()
    assert ((u.n_active==0)==u.vacant).all()
    assert (u.vacant & u.vacant_days.between(90,1095)).equals(u.recent_vacancy)
    live=(~u.vacant)|(u.vacant_days<=1095)
    groups=[]
    for low in (30,60,90,180):
        candidate=u.vacant & u.vacant_days.between(low,1095)
        groups.append({'min_days':low,'denominator':int(live.sum()),'candidates':int(candidate.sum()),'pct':round(100*candidate.sum()/live.sum(),2)})
    cohorts=[]
    for year in (2000,2010,2015,2020):
        f=st[st.ld.dt.year>=year]
        summary=survival.summarize(f.dur_days,f.closed)
        summary.pop('curve')
        cohorts.append({'start_year':year,**summary,'at_risk_1y':int(f.dur_days.ge(365.25).sum()),'at_risk_3y':int(f.dur_days.ge(3*365.25).sum()),'at_risk_5y':int(f.dur_days.ge(5*365.25).sum())})
    # Independent tiny examples for event/censoring ties and inadequate follow-up.
    t,s=survival.kaplan_meier([10,10,20],[True,False,True])
    assert abs(survival.survival_at(t,s,10)-2/3)<1e-10
    assert survival.survival_at(t,s,20)==0
    assert survival.summarize([100,200],[False,False])['survival_1y_pct'] is None
    boundary=pd.Series([89,90,1095,1096]).between(90,1095).tolist()
    assert boundary==[False,True,True,False]
    counts={'stores':len(st),'closed':int(st.closed.sum()),'active':int((~st.closed).sum()),
            'closed_missing_date':int((st.closed & st.cd.isna()).sum()),'active_with_close_date':int((~st.closed & st.cd.notna()).sum()),
            'same_day_closures':int((st.closed & st.ld.eq(st.cd)).sum()),
            'vacancy_denominator':int(live.sum()),'vacancy_candidates':int(u.recent_vacancy.sum()),
            'vacant_under_90_in_denominator':int((live & u.vacant & u.vacant_days.lt(90)).sum()),
            'live_missing_gu':int((live & u.gu.isna()).sum()),'live_missing_gu_or_dong':int((live & (u.gu.isna()|u.dong.isna())).sum()),
            'survival_rows_reproduced':len(saved),'vacancy_rows_reproduced':len(vac)}
    payload={'reference_date':str(ref.date()),'counts':counts,'vacancy_sensitivity':groups,'cohort_sensitivity':cohorts,
             'source_hashes':{name:hashlib.sha256((DEMO/name).read_bytes()).hexdigest() for name in ['pipeline/build.py','core/survival.py','config.py']},
             'checks':'input hashes; full survival/vacancy table comparison; derived duration/vacant/candidate identities; 3 KM checks; inclusive vacancy boundary'}
    out=ROOT/'docs/d02'
    (out/'outcome_audit.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-02 폐업·공실·생존 정의 검증','',f'가공본 기준일: {ref.date()}. 원본 CSV 및 원본 영업상태 문자열이 없어 상태 분류 이전 단계의 정확도는 독립 재현하지 못한다.','',
           '## 확인 결과','','```text',json.dumps(counts,ensure_ascii=False,indent=2),'```','',
           '- 원천 코드에서는 영업상태에 폐업·취소·말소가 포함되면 사건으로 처리한다. 폐업일이 없으면 인허가취소일을 사용한다. 현재 가공본의 closed와 날짜 일관성만 확인했으며 실제 영업·폐업 확인은 아니다.',
           '- 영업 중 기록은 기준일에서 관측을 끊으며 사건으로 세지 않는다. 당일 폐업은 관측기간 0일의 사건이다.',
           '- 공실 후보는 n_active=0 및 마지막 종료 후 90~1095일(양 끝 포함)이다. 달력상 정확히 3년과 고정 1095일은 윤년에 차이가 날 수 있다.',
           '- 공실 분모는 영업 중 또는 종료 후 1095일 이하 자리다. 종료 후 90일 미만은 분모에는 들어가지만 후보 분자에는 안 들어가므로 occupied+vacant 후보가 분모와 같지 않을 수 있다.',
           '- 지역 집계는 groupby 기본값 때문에 지역키 결측이 제외된다. 아래 전체 분모와 지역별 합계를 무조건 같다고 가정하지 않는다.',
           '- 공실 집계는 is_single_unit 필터를 사용하지 않는다. 따라서 다점포 건물/층을 포함한 등록 업종의 공실 후보율이며 실제 임대 공실률이 아니다.',
           '', '## 공실 최소 일수 민감도', '', '```text',pd.DataFrame(groups).to_string(index=False),'```','',
           '## 생존 코호트 시작연도 민감도','','```text',pd.DataFrame(cohorts).to_string(index=False),'```','',
           '- 시작연도 변경은 모집단·관측기간을 함께 바꾼다. 차이를 업종 성과 향상/악화나 인과 효과로 해석하지 않는다.',
           '- 2010년 기준과 n>=30은 현재 구현의 선택이며 편향 해소 또는 통계적 신뢰성을 보장하지 않는다.',
           '- 표본은 자리 수가 아닌 인허가 기록 수다. 같은 uid 기록의 의존성을 고려하지 않은 구간 추정·검정은 별도 검토가 필요하다.',
           '- at_risk는 해당 기간 이상 실제 관측된 기록 수다. 전체 표본 30개를 넘더라도 장기 시점의 위험집단은 작을 수 있다. 현재 summarize는 최대 관측기간만 확인한다.',
           '', '## 재현·검증 범위','','저장된 생존 요약표 전체와 공실 지역표 전체를 실제 생성 함수로 다시 계산해 대조했다. 사건/중도절단 동률을 포함한 작은 예제와 89·90·1095·1096일 경계를 확인했다. 계산 재현은 정의의 현실 타당성을 증명하지 않는다.',
           '', '## 다음 작업','','주소·층·업종 별칭 및 구·동·업종·개업연도별 EDA, 누락률·작은 집단·관측기간 비교가 남아 있다. 최종 사용 제한 목록과 학생 해석을 합친 뒤 D-02를 마무리한다.',
           '', '재현: `python scripts/audit_d02_outcomes.py` (D-01 분석 환경).','']
    (out/'outcome_audit.md').write_text('\n'.join(line.rstrip() for line in lines),encoding='utf-8')
    print(json.dumps({'counts':counts,'vacancy_sensitivity':groups,'cohort_sensitivity':cohorts},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
