"""Compare annual permit/closure counts with explicit partial-year labels."""
import hashlib
import json
import pandas as pd
from audit_d02_units import ROOT,DEMO


def main():
    data=DEMO/'data/processed'
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((data/name).read_bytes()).hexdigest()==digest,name
    st=pd.read_parquet(data/'stores.parquet')
    ref=pd.Timestamp(manifest['reference_date'])
    tables={}
    for label,keys in [('gu',['gu']),('dong',['gu','dong']),('service',['service'])]:
        opens=st.assign(year=st.ld.dt.year).groupby(keys+['year'],dropna=False).size().rename('opens')
        closed=st[st.closed]
        closes=closed.assign(year=closed.cd.dt.year).groupby(keys+['year'],dropna=False).size().rename('closes')
        frame=pd.concat([opens,closes],axis=1).fillna(0).astype(int).reset_index()
        frame['partial_year']=frame.year.eq(ref.year)
        frame['small_event_count']=frame.opens.add(frame.closes).lt(30)
        assert int(frame.opens.sum())==len(st)
        assert int(frame.closes.sum())==int(st.closed.sum())
        tables[label]=json.loads(frame.to_json(orient='records',force_ascii=False))
    # Match calendar windows rather than comparing partial 2026 with full 2025.
    windows=[]
    for year in (2024,2025,2026):
        start=pd.Timestamp(year,1,1);stop=pd.Timestamp(year,ref.month,ref.day)+pd.Timedelta(days=1)
        for label,keys in [('gu',['gu']),('service',['service'])]:
            op=st[st.ld.ge(start)&st.ld.lt(stop)].groupby(keys,dropna=False).size().rename('opens')
            cl=st[st.closed&st.cd.ge(start)&st.cd.lt(stop)].groupby(keys,dropna=False).size().rename('closes')
            f=pd.concat([op,cl],axis=1).fillna(0).astype(int).reset_index()
            for row in json.loads(f.to_json(orient='records',force_ascii=False)):
                windows.append({'level':label,'year':year,'window_start':str(start.date()),'window_end_inclusive':str((stop-pd.Timedelta(days=1)).date()),**row})
    out=ROOT/'docs/d02'
    payload={'reference_date':str(ref.date()),'annual':tables,'same_calendar_window':windows,'checks':'14 input hashes; opens/closes totals match at all 3 grouping levels'}
    (out/'annual_comparison.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# D-02 지역·업종별 사건 연도 비교','',f'기준일 {ref.date()}. 각 연도의 개업일·폐업일을 기준으로 집계한다. 개업 코호트별 누적 폐업 수와 다르다.', '',
           '## 검증과 해석 제한','','- 구·동·업종 각각 지역 결측 그룹을 포함했으며 전 기간 개업 합계 197,356건, 폐업 합계 138,307건과 일치한다.',
           '- 전체 연도 상세 표는 annual_comparison.json에 보존했다. 개업+폐업 사건 30건 미만에는 작은 집단 표시를 붙였다.',
           '- 2026년은 9월 23일까지다. 아래는 2024~2026년을 각각 1월 1일~9월 23일로 맞춘 표다. 윤년 2024년은 하루 더 길며 일당 발생률로 보정한 표는 아니다.',
           '- 같은 달력 구간이어도 원천 등록 누락·신고 지연·업종 구성·지역 경계 변화는 통제되지 않는다. 단순 건수 차이를 폐업 위험 변화로 해석하지 않는다.',
           '- 분모가 위험에 노출된 점포 수나 점포-시간이 아니므로 폐업률을 계산하지 않았다. 증감은 사건 건수 비교에 한정한다.', '', '## 같은 달력 구간 비교','','```text',pd.DataFrame(windows).to_string(index=False),'```','',
           '재현: `python scripts/audit_d02_annual.py` (D-01 분석 환경).','']
    (out/'annual_comparison.md').write_text('\n'.join(line.rstrip() for line in lines),encoding='utf-8')
    print(json.dumps({'annual_rows':{k:len(v) for k,v in tables.items()},'window_rows':len(windows),'checks':'PASS'},ensure_ascii=False))

if __name__=='__main__':main()
