"""Inspect administrative-area context without equating rule labels with land use."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from join_a01_poi import distances
from analyze_a01_hypothesis import correlation

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/a01'


def main():
    time_path=OUT/'time_slots.json';loc_path=OUT/'station_locations.json'
    t=json.loads(time_path.read_text(encoding='utf-8'))
    locations=json.loads(loc_path.read_text(encoding='utf-8'))
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    paths=[ROOT/'service/data/processed'/n for n in ['poi.parquet','area_context.parquet']]
    for p in paths:
        assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['sha256'][p.name]
    assert hashlib.sha256((OUT/'hypothesis.json').read_bytes()).hexdigest()==t['input_hashes']['hypothesis.json']
    poi=pd.read_parquet(paths[0]);context=pd.read_parquet(paths[1])
    assert not context.duplicated(['gu','admin_dong']).any()
    ctx=context.set_index(['gu','admin_dong'])
    base=pd.DataFrame(t['station_results'])
    base=base[(base.radius_m==300)&(base['mode']=='raw')]
    assert base.station.is_unique
    assert len(base)==t['primary_n']
    exit_map={g['traffic_station']:g for g in locations['station_exit_groups'] if g['traffic_match'] and not g['review_cluster']}
    lat,lon=poi.lat.to_numpy(),poi.lon.to_numpy()
    out=[]
    for _,row in base.iterrows():
        nearest=np.full(len(poi),np.inf)
        for point in exit_map[row.station]['points']:
            nearest=np.minimum(nearest,distances(lat,lon,point['latitude'],point['longitude']))
        for radius in [300,500]:
            nearby=poi[nearest<=radius]
            ref=next(r for r in t['station_results'] if r['station']==row.station and r['radius_m']==radius and r['mode']=='raw')
            assert len(nearby)==ref['denominator'], 'Spatial join changed'
            known=nearby.dropna(subset=['gu','admin_dong'])
            counts=known.groupby(['gu','admin_dong']).size().sort_values(ascending=False)
            if counts.empty:
                raise ValueError(f'No area name: {row.station}')
            maximum=int(counts.iloc[0]);ties=int((counts==maximum).sum())
            # Lexical order only stabilizes output in ties; tied assignments are excluded from summaries.
            keys=sorted(counts[counts==maximum].index.tolist());key=keys[0]
            exists=key in ctx.index
            c=ctx.loc[key] if exists else None
            out.append({'station':row.station,'radius_m':radius,'nearby_poi_rows':len(nearby),
                        'missing_area_rows':len(nearby)-len(known),'area_count':len(counts),
                        'dominant_gu':key[0],'dominant_admin_dong':key[1],
                        'dominant_share_pct':maximum/len(nearby)*100,'tied_dominant_areas':ties,
                        'context_matched':exists,'area_population':int(c.pop_total) if exists else None,
                        'population_reference':str(c.pop_ref_month) if exists else None,
                        'rule_market_type':str(c.market_type) if exists else None,
                        'rule_basis':str(c.market_type_basis) if exists else None,
                        'evening_pct':float(row.evening_17_20_pct),'quick_pct':float(ref['quick_pct']),
                        'area_distribution':[{'gu':a,'admin_dong':b,'poi_rows':int(n)} for (a,b),n in counts.items()]})
    d=pd.DataFrame(out)
    summaries=[]
    for radius in [300,500]:
        for cutoff in [50,80]:
            part=d[(d.radius_m==radius)&d.context_matched&(d.tied_dominant_areas==1)&(d.dominant_share_pct>cutoff)]
            split=float(part.evening_pct.median()) if len(part) else None
            groups=[]
            for name,q in [('low_or_equal',part[part.evening_pct<=split]),('high',part[part.evening_pct>split])]:
                n=len(q);res=int((q.rule_market_type=='주거상권').sum())
                groups.append({'group':name,'n':n,'rule_residential_n':res,
                               'rule_residential_pct':100*res/n if n else None,
                               'median_area_population':float(q.area_population.median()) if n else None})
            summaries.append({'radius_m':radius,'dominant_share_cutoff_strict_pct':cutoff,'n':len(part),
                              'unique_admin_areas':len(part[['dominant_gu','dominant_admin_dong']].drop_duplicates()),
                              'evening_median_pct':split,'evening_population_spearman':correlation(part.evening_pct,part.area_population),
                              'groups':groups})
    result={'checked_date':'2026-10-12','purpose':'exploratory context check, not residential land-use validation',
            'mapping':'dominant administrative area among buffered POI rows; not station polygon containment',
            'input_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [time_path,loc_path,*paths]},
            'station_rows':out,'summaries':summaries,
            'missing_context_rows':int((~d.context_matched).sum()),
            'limits':['population is entire administrative area, not 300m residents or density',
                      'market_type depends on food composition; not independent evidence for quick-food hypothesis',
                      'multiple stations can share same area; no independent-observation inference',
                      'dominant area is POI-count proxy, not measured residential land use']}
    (OUT/'residential_context.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# A-01 저녁 하차와 주변 행정동 맥락','','2026-10-12 · 김선경 · 탐색적 참고 지표 비교','',
           '## 질문과 자료 한계','',
           '저녁 하차 비중이 높은 역이 주거지역에 있는지 확인하려 했다. 현재 데이터에는 주거용 건물 비율·토지이용·격자별 인구가 없어 직접 검증할 수 없다. 대신 주변 상가가 주로 속한 행정동의 인구와 기존 상권 규칙 분류를 확인했다.',
           '- 주민등록 인구 기준: 가공본 pop_ref_month = 2026-08-31. 행정동 전체 인구이며 역 300m 인구나 인구밀도가 아니다.',
           '- 기존 주거상권 규칙: 수리·개인서비스+보건 비중이 도시 평균의 1.1배 이상이고 음식 비중이 도시 평균 이하이며 앞선 우선 규칙에 해당하지 않을 때. 음식 비중을 사용하므로 간편식 가설의 독립 증거가 아니다.',
           '- 역 주변 POI의 (구, 행정동) 최빈값을 연결했다. 이는 역 좌표를 행정경계에 대조한 것이 아니다. 동률은 요약에서 제외한다.',
           '- 한 행정동 비중 >50%를 기본 참고집합, >80%를 민감도 집합으로 비교했다. 임시 대표성 기준이며 공인 주거지역 판정 기준이 아니다.', '',
           '## 높은/낮은 저녁 하차 비중 그룹 비교','',
           '각 조건의 저녁 하차 비중 중앙값으로 그룹을 나눈다. 기존 규칙 분류 비율은 실제 주거지역 비율이 아니다.', '',
           '| 반경 | 대표 동 비중 | 역 수 / 고유 동 수 | 낮은 그룹: 규칙상 주거 | 높은 그룹: 규칙상 주거 | 인구와 저녁 비중 순위상관 |',
           '| --- | --- | --- | --- | --- | ---: |']
    for s in summaries:
        lo,hi=s['groups'];rho=s['evening_population_spearman']
        lines.append(f"| {s['radius_m']}m | >{s['dominant_share_cutoff_strict_pct']}% | {s['n']} / {s['unique_admin_areas']} | {lo['rule_residential_n']}/{lo['n']} | {hi['rule_residential_n']}/{hi['n']} | {rho:.3f} |")
    lines += ['', '## 저녁 하차 비중 상위 10개 역의 실제 연결 사례','',
              '| 역 | 저녁 하차 비중 | 대표 행정동 | 주변 상가 중 해당 동 비중 | 행정동 전체 인구 | 기존 규칙 분류 |',
              '| --- | ---: | --- | ---: | ---: | --- |']
    for _,r in d[d.radius_m==300].sort_values(['evening_pct','station'],ascending=[False,True]).head(10).iterrows():
        lines.append(f"| {r.station} | {r.evening_pct:.1f}% | {r.dominant_gu} {r.dominant_admin_dong} | {r.dominant_share_pct:.1f}% | {r.area_population:,} | {r.rule_market_type} |")
    lines += ['', '## 결론의 범위','',
              '이 비교만으로 귀가 수요나 주거지역 가설을 입증할 수 없다. 독립적인 주거용 건축물 면적 비율·주거지역 경계·격자 인구 중 하나를 확보해 동일한 300m 범위로 비교하는 단계가 필요하다. 같은 행정동에 속한 여러 역의 인구는 독립 표본으로 해석하지 않는다.',
              '앞선 시간대 관계는 유지하되 원인 설명은 미확정으로 남긴다. A-01 완료 처리하지 않는다.', '',
              '재현: `.venv/Scripts/python scripts/analyze_a01_residential_context.py`. 역별 행정동 분포·기존 규칙 근거·입력 해시는 residential_context.json에 기록. 원본·서비스 데이터 변경 없음.']
    (OUT/'residential_context.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'summaries':summaries,'missing_context_rows':result['missing_context_rows']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
