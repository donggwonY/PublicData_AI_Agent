"""Reproducible read-only address, alias and stratified EDA audit."""
import ast
import hashlib
import importlib.util
import json
from types import SimpleNamespace
import numpy as np
import pandas as pd
from audit_d02_units import ROOT, DEMO


def extract(path, names, ns):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)


def main():
    data=DEMO/'data/processed'
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    for name,value in manifest['sha256'].items():
        assert hashlib.sha256((data/name).read_bytes()).hexdigest()==value,name
    st=pd.read_parquet(data/'stores.parquet')
    ref=pd.Timestamp(manifest['reference_date'])
    ns={'pd':pd,'np':np,'FLOOR_DOMINANCE':0.8}
    extract(DEMO/'pipeline/build.py',{'assign_floor_units'},ns)
    rebuilt=ns['assign_floor_units'](st)
    assert (rebuilt==st.uid.to_numpy()).all(), '80% floor rule differs from saved uid'
    floors=[]
    for cutoff in (0.6,0.8,1.0):
        ns['FLOOR_DOMINANCE']=cutoff
        uid=pd.Series(ns['assign_floor_units'](st),index=st.index)
        floors.append({'dominance':cutoff,'unique_units':int(uid.nunique()),'changed_records':int(uid.ne(st.uid).sum()),
                       'missing_floor_assigned':int((st.floor.isna() & uid.ne(st.building_key)).sum())})
    spec=importlib.util.spec_from_file_location('audit_address',DEMO/'core/address.py')
    address=importlib.util.module_from_spec(spec);spec.loader.exec_module(address)
    floor=pd.Series([address.extract_floor(r,j) for r,j in zip(st.road_addr_raw,st.jibun_addr_raw)],index=st.index)
    assert floor.fillna('<missing>').eq(st.floor.fillna('<missing>')).all()
    # Verify stable normalization examples without implying physical shop identity.
    assert address.parse_jibun('대구광역시 중구 삼덕동1가 0028-0006 2층')['key']==address.parse_jibun('대구 중구 삼덕동1가 28-6')['key']
    cfg={}
    for node in ast.parse((DEMO/'config.py').read_text(encoding='utf-8')).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'SERVICES','CATEGORY_ALIASES'} for t in node.targets):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'config.py','exec'),{},cfg)
    categories=sorted(st.category.dropna().unique())
    context={'C':SimpleNamespace(**cfg),'store':lambda:SimpleNamespace(categories=categories),'ToolError':ValueError}
    extract(DEMO/'core/tools.py',{'_resolve_category'},context)
    aliases=[]
    for alias,configured in cfg['CATEGORY_ALIASES'].items():
        try:
            service,cats,label=context['_resolve_category'](alias)
            mask=st.service.eq(service) if service else st.category.isin(cats)
            aliases.append({'input':alias,'service':service,'resolved':cats,'configured':configured,'n':int(mask.sum()),'unavailable':False})
        except ValueError:
            aliases.append({'input':alias,'service':None,'resolved':[],'configured':configured,'n':0,'unavailable':True})
    st=st.assign(open_year=st.ld.dt.year,missing_coord=st.lat.isna()|st.lon.isna(),missing_floor=st.floor.isna(),
                 missing_area=st.gu.isna()|st.dong.isna(),followup_days=(ref-st.ld).dt.days)
    tables={}
    for name,keys in [('gu',['gu']),('dong',['gu','dong']),('service',['service']),('category',['category']),('open_year',['open_year'])]:
        g=st.groupby(keys,dropna=False).agg(n=('uid','size'),closed=('closed','sum'),unique_units=('uid','nunique'),
            missing_coord_pct=('missing_coord','mean'),missing_floor_pct=('missing_floor','mean'),missing_area_pct=('missing_area','mean'),
            median_observed_days=('dur_days','median'),median_possible_followup_days=('followup_days','median'))
        for col in ['missing_coord_pct','missing_floor_pct','missing_area_pct']:g[col]=(100*g[col]).round(2)
        g['active']=g.n-g.closed
        g['cumulative_closed_pct']=(100*g.closed/g.n).round(2)
        g['small_n_under_30']=g.n<30
        assert int(g.n.sum())==len(st)
        tables[name]=json.loads(g.reset_index().to_json(orient='records',force_ascii=False))
    # Event-year counts are different from closure outcomes grouped by opening year.
    opens=st.groupby(st.ld.dt.year).size()
    closes=st[st.closed].groupby(st.loc[st.closed,'cd'].dt.year).size()
    annual=pd.concat([opens.rename('opens'),closes.rename('closes')],axis=1).fillna(0).astype(int).rename_axis('year').reset_index()
    annual['partial_year']=annual.year.eq(ref.year)
    assert annual.opens.sum()==len(st) and annual.closes.sum()==st.closed.sum()
    tables['event_year']=json.loads(annual.to_json(orient='records'))
    summary={'rows':len(st),'floor_missing':int(st.floor.isna().sum()),'small_groups':{name:sum(r['small_n_under_30'] for r in rows) for name,rows in tables.items() if name!='event_year'},
             'aliases_unavailable':[r['input'] for r in aliases if r['unavailable']],
             'exact_category_preempts_alias':[r['input'] for r in aliases if r['input'] in categories and set(r['resolved'] or [])!=set(c for c in r['configured'] if c in categories)]}
    out=ROOT/'docs/d02'
    payload={'reference_date':str(ref.date()),'summary':summary,'floor_sensitivity':floors,'aliases':aliases,'tables':tables,
             'source_hashes':{name:hashlib.sha256((DEMO/name).read_bytes()).hexdigest() for name in ['pipeline/build.py','core/address.py','core/tools.py','config.py']}}
    (out/'eda_audit.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-02 주소·층·별칭과 탐색 분석','',f'기준일 {ref.date()}. D-01 입력 14개 해시 확인. 원본·운영 코드 변경 없음.','',
           '## 주소·층 검증','','저장 주소에서 층을 재추출한 결과와 floor 전체 일치. 80% 층 보충 규칙으로 재계산한 uid도 전체 일치. 지번 앞자리 0·대구 약칭 정규화 예제 통과. 이는 물리적 호수·점포 경계 정확성 확인이 아니다.','','```text',pd.DataFrame(floors).to_string(index=False),'```','',
           '층이 없는 행에 같은 건물의 우세 층을 보충하는 비율을 변경했다. uid 변경 건수는 행 기준이며 서로 다른 자리 개수와 구분한다. 이 실험에서는 시간 겹침과 공실·전이를 다시 계산하지 않았다. 전체 기록으로 학습하는 층 보충은 과거 예측에 사용하기 전에 미래 정보 영향을 점검해야 한다.','',
           '## 별칭 검증','','```text',pd.DataFrame(aliases)[['input','service','resolved','n','unavailable']].to_string(index=False),'```','',
           '조회 함수는 업종명 → 정확한 업태명 → 별칭 → 부분문자열 순서로 해석한다. 따라서 설정에 별칭이 있어도 정확한 업태명과 같으면 확장되지 않을 수 있다. 조회 결과에는 실제 합친 업태를 표시해야 하며, 일상어 별칭을 서로 배타적인 업종으로 합산하지 않는다. 조회 불가를 점포 0개로 해석하지 않는다.','',
           '## 지역·업종·개업연도 탐색','','모든 표는 지역 결측 그룹도 보존하며 각 표의 n 합계가 전체 197,356건과 일치한다. closed는 해당 집단에서 기준일까지 누적된 폐업 수다. 누적 폐업 비율은 연간 폐업률·생존 확률이 아니다. unique_units는 그룹 사이에 중복될 수 있어 합산하지 않는다.','',
           '```text',json.dumps(summary,ensure_ascii=False,indent=2),'```','']
    for name in ['gu','service','open_year','event_year']:
        lines+=['### '+name,'','```text',pd.DataFrame(tables[name]).to_string(index=False),'```','']
    lines+=['동·업태 전체 표는 eda_audit.json의 tables.dong/category에 저장했다. 작은 집단 기준 n<30은 검토용 표시이며 30 이상을 신뢰 가능으로 보증하지 않는다.', '',
            'median_observed_days는 사건/중도절단까지 관측된 기간, median_possible_followup_days는 개업일부터 공통 기준일까지의 가능 추적기간이다. 최근 개업 집단은 관측기간이 짧아 단순 누적 폐업 비율을 오래된 집단과 비교하면 안 된다. 2026년 사건 집계는 9월 23일까지의 부분연도이며 완전 연도와 직접 비교하지 않는다.', '',
            '## 남은 판단','','현재 법정동/행정동 대표 매핑의 역사적 타당성은 D-01의 보류 사항을 유지한다. 원본 누락률은 계산할 수 없어 가공본 내부 결측률과 구분한다. 정의별 권고·사용 제한·키/기준일 전달 문서 및 학생 해석을 통합한 뒤 완료 판단한다.', '',
            '재현: `python scripts/audit_d02_eda.py` (D-01 분석 환경).','']
    (out/'eda_audit.md').write_text('\n'.join(line.rstrip() for line in lines),encoding='utf-8')
    print(json.dumps({'summary':summary,'floor_sensitivity':floors},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
