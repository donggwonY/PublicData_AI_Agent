"""Compare time-of-day alighting composition with quick-food POI composition."""
from pathlib import Path
import hashlib
import json
import pandas as pd
from analyze_a01_hypothesis import correlation, plt, font_manager

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/a01'
FEATURES={'daily_total':'일평균 전체 승차+하차', 'lunch_11_14_pct':'11~14시 하차 비중', 'evening_17_20_pct':'17~20시 하차 비중'}


def main():
    hpath=OUT/'hypothesis.json';tpath=ROOT/'service/data/processed/station_traffic.parquet'
    original=json.loads(hpath.read_text(encoding='utf-8'))
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(tpath.read_bytes()).hexdigest()==manifest['sha256'][tpath.name]
    assert hashlib.sha256((OUT/'poi_join.json').read_bytes()).hexdigest()==original['input_sha256']
    d=pd.DataFrame(original['station_results'])
    d=d[(~d.transfer)&(~d.coverage.isin(['exclude_outside_daegu','border_review']))&(d.denominator>0)]
    traffic=pd.read_parquet(tpath)
    assert traffic.station.is_unique
    d=d.merge(traffic[['station','lunch_11_14_pct','evening_17_20_pct']],on='station',how='left',validate='many_to_one',indicator=True)
    assert d['_merge'].eq('both').all()
    assert d[['lunch_11_14_pct','evening_17_20_pct']].notna().all().all()
    assert d[['lunch_11_14_pct','evening_17_20_pct']].ge(0).all().all() and d[['lunch_11_14_pct','evening_17_20_pct']].le(100).all().all()
    stats=[]
    for radius in (300,500):
        for mode in ('raw','exact_deduplicated'):
            for scenario in ('all_available','min_30_rows'):
                part=d[(d.radius_m==radius)&(d['mode']==mode)]
                if scenario=='min_30_rows':part=part[part.denominator>=30]
                for feature,label in FEATURES.items():
                    stats.append({'radius_m':radius,'mode':mode,'scenario':scenario,'feature':feature,'label':label,'n':len(part),'spearman_quick_pct':correlation(part[feature],part.quick_pct)})
    primary=d[(d.radius_m==300)&(d['mode']=='raw')].copy()
    medians=[]
    for feature in ('lunch_11_14_pct','evening_17_20_pct'):
        middle=float(primary[feature].median())
        lo=primary[primary[feature]<=middle];hi=primary[primary[feature]>middle]
        medians.append({'feature':feature,'split_pct':middle,'low_n':len(lo),'high_n':len(hi),
                        'low_quick_pct_median':float(lo.quick_pct.median()),'high_quick_pct_median':float(hi.quick_pct.median())})
    result={'checked_date':'2026-10-12','student_interpretation':'카페는 커피/음료만 있으니까 배 채울려면 간편식이 더 관련이 있을테니까?',
            'followup_hypothesis':'점심·퇴근 시간대 하차 비중이 높은 역에서 간편식 비중이 더 높을까?',
            'primary_n':len(primary),'excluded_transfers':['반월당','명덕','청라언덕'],
            'definition':'time share = interval alighting / available 05-24h alighting; outcome = quick-food POI rows / all POI rows',
            'no_imputed_transfer_shares':True,'statistics':stats,'median_splits':medians,
            'input_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [hpath,tpath]},
            'station_results':json.loads(d.drop(columns=['_merge']).to_json(orient='records',force_ascii=False)),
            'limitations':['No travel purpose observed','Relative shares, not time-specific patron counts','Exploratory post-hoc hypothesis','Spatial overlap and period/datum uncertainty retained']}
    (OUT/'time_slots.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    selected=[s for s in stats if s['scenario']=='all_available' and s['mode']=='raw']
    lines=['# A-01 후속 탐색: 시간대별 하차 비중과 간편식 비중','','2026-10-12 · 김선경 · 탐색 결과','',
           '## 학생 해석과 후속 질문','','학생은 이동 중 식사를 해결하는 수요 때문에 카페보다 간편식과 관련될 수 있다고 해석했다. 이는 관측 결과의 설명 가설이며 실제 방문 목적은 확인되지 않았다.',
           '후속 질문: 점심(11~14시)·퇴근 시간대(17~20시) 하차 비중이 높은 역에서 간편식 비중이 높은가?', '',
           '## 비교 정의','',
           '- 간편식: 김밥/만두/분식·버거·토스트/샌드위치/샐러드·빵/도넛. 분모는 범위 내 전체 POI 행.',
           '- 시간대 비중: 각 구간 하차 합 / 사용 가능한 05~24시 하차 합. 승차는 포함하지 않는다. 가공본의 소수 첫째자리 반올림을 유지한다.',
           '- 환승역 3개(반월당·명덕·청라언덕)는 원래 시간대 분모가 없어 제외한다. 일평균 하차수로 임의 가중평균하지 않는다.',
           '- 경산권 3역·사월 및 출구 미연결 4항목 제외는 선행 분석과 같다. 전체 이용량도 같은 80개 역에서 다시 비교한다.',
           '- 17~20시는 시간 구간 명칭일 뿐, 해당 하차가 모두 퇴근 목적이라고 가정하지 않는다.', '',
           '## 전체 표본 비교(원본 POI 행)','', '| 반경 | 비교 변수 | 역 수 | 간편식 비중과 순위 상관 |','| --- | --- | ---: | ---: |']
    for s in selected:lines.append(f"| {s['radius_m']}m | {s['label']} | {s['n']} | {s['spearman_quick_pct']:.3f} |")
    lines += ['', '## 민감도 점검', '', '| 반경 | 동일행 처리 | 표본 조건 | 역 수 | 점심 | 17~20시 |', '| --- | --- | --- | ---: | ---: | ---: |']
    for radius in (300,500):
        for mode in ('raw','exact_deduplicated'):
            for scenario in ('all_available','min_30_rows'):
                group=[s for s in stats if s['radius_m']==radius and s['mode']==mode and s['scenario']==scenario]
                lunch=next(s for s in group if s['feature']=='lunch_11_14_pct');evening=next(s for s in group if s['feature']=='evening_17_20_pct')
                lines.append(f"| {radius}m | {mode} | {scenario} | {lunch['n']} | {lunch['spearman_quick_pct']:.3f} | {evening['spearman_quick_pct']:.3f} |")
    lines += ['', '## 해석 제한','',
              '- 비중이 높다고 실제 그 시간대 하차 인원 또는 간편식 구매자가 많다는 뜻은 아니다. 구매·방문 목적·매출 데이터는 없다.',
              '- 앞선 결과를 보고 만든 후속 가설이다. 새 독립 데이터의 확인 검증으로 표현하지 않는다.',
              '- 공간 중복·자료 시점 차이·좌표계 및 경계 불확실성이 남아 있어 유의성/인과 주장을 하지 않는다.',
              '- 지역 유형, 대학·직장·주거지, 업종 분류와 시간대 구성의 관계는 통제하지 않았다. 카페와의 차이를 이 비교 하나로 설명할 수 없다.',
              '- 전체 이용량과 시간대 비중은 다른 변수다. 둘의 상관 크기만으로 어떤 원인이 더 중요하다고 판단하지 않는다.', '',
              '재현: `.venv/Scripts/python scripts/analyze_a01_time_slots.py`. 입력 해시·역별 값은 time_slots.json, 산점도는 time_slots.png. A-01은 진행 상태 유지.']
    (OUT/'time_slots.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    font=Path('C:/Windows/Fonts/malgun.ttf')
    if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']='Malgun Gothic'
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(11,5.3),sharey=True)
    for ax,feature in zip(axes,['lunch_11_14_pct','evening_17_20_pct']):
        stat=next(s for s in selected if s['radius_m']==300 and s['feature']==feature)
        ax.scatter(primary[feature],primary.quick_pct,s=34,color='#146b81',alpha=.8,edgecolors='white',linewidths=.4)
        ax.set_title(f"{FEATURES[feature]} · n={len(primary)}\n순위 상관 {stat['spearman_quick_pct']:.3f}")
        ax.set_xlabel('해당 시간대 하차 / 05~24시 하차 (%)');ax.grid(alpha=.2);ax.set_axisbelow(True)
    axes[0].set_ylabel('출구 300m 전체 상가 중 간편식 비중 (%)')
    fig.suptitle('식사 시간대 하차 비중과 간편식 비중은 관련이 있을까?',fontsize=14)
    fig.text(.5,.018,'환승역 제외 · 방문 목적 미관측 · 공간/시점 한계 유지 · 탐색 결과이며 인과 해석 불가',ha='center',fontsize=9,color='#555')
    fig.tight_layout(rect=[0,.05,1,.93]);fig.savefig(OUT/'time_slots.png',dpi=160);plt.close(fig)
    print(json.dumps({'primary':selected,'median_splits':medians},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
