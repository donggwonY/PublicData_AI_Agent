import unittest
import io
import pandas as pd
from core.permit_trends import summarize_permit_trends, permit_trends_csv, compare_industry_regions
from streamlit.testing.v1 import AppTest

def fixture():
    rows = [
        ('의원','중구','2022-01-01',None,False),
        ('병원','중구','2022-01-02','2023-01-01',True),
        ('미용업','중구','2020-01-01','2022-01-01',True),
        ('미용업','중구','2023-01-02',None,False),
        ('약국','남구','2022-06-01',None,False),
        ('약국','중구','2020-01-01',None,True),
    ]
    f=pd.DataFrame(rows,columns=['service','gu','ld','cd','closed'])
    f['uid']='shared';f['ld']=pd.to_datetime(f.ld);f['cd']=pd.to_datetime(f.cd)
    return f

class PermitTrendTests(unittest.TestCase):
    def test_boundaries_grouping_and_invalid_dates(self):
        f=fixture();original=f.copy(deep=True)
        r=summarize_permit_trends(f,'2023-01-01','중구');g={x['industry']:x for x in r['rows']}
        self.assertEqual(g['의원·병원']['opened'],1)
        self.assertEqual(g['의원·병원']['closure_reports'],1)
        self.assertEqual(g['의원·병원']['active_permits'],1)
        self.assertEqual(g['미용업']['opened'],0)
        self.assertEqual(g['미용업']['closure_reports'],0)
        self.assertEqual(g['미용업']['previous_closure_reports'],1)
        self.assertEqual(g['의원·병원']['previous_opened'],1)
        self.assertEqual(r['excluded_date_rows'],1)
        self.assertEqual(g['의원·병원']['active_share_pct'],100)
        pd.testing.assert_frame_equal(f,original)

    def test_export_scope_and_dates(self):
        r=summarize_permit_trends(fixture(),'2023-01-01','중구')
        data=permit_trends_csv(r,'중구','의원·병원')
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        frame=pd.read_csv(io.BytesIO(data))
        self.assertEqual(len(frame),1)
        self.assertEqual(frame.iloc[0]['industry'],'의원·병원')
        self.assertEqual(frame.iloc[0]['region'],'중구')
        self.assertEqual(frame.iloc[0]['previous_period_end'],'2022-01-01')
        self.assertEqual(frame.iloc[0]['opened'],1)

    def test_region_comparison_denominator_and_missing_industry(self):
        f=fixture()
        typo=f.iloc[[0]].copy(); typo['gu']='님구'
        f=pd.concat([f,typo],ignore_index=True)
        result=compare_industry_regions(f, '2023-01-01', '의원·병원').set_index('region')
        self.assertNotIn('님구',result.index)
        self.assertEqual(result.loc['중구','active_permits'], 1)
        self.assertEqual(result.loc['중구','active_share_pct'], 100)
        self.assertEqual(result.loc['중구','opened_change'], 0)
        self.assertEqual(result.loc['남구','active_permits'], 0)
        self.assertEqual(result.loc['남구','active_share_pct'], 0)
        # With no active denominator, a share must not imply a measured zero.
        f['short_event']=f.gu.eq('남구')
        result=compare_industry_regions(f, '2023-01-01', '의원·병원').set_index('region')
        self.assertTrue(pd.isna(result.loc['남구','active_share_pct']))

    def test_unknown_region_empty(self):
        self.assertEqual(summarize_permit_trends(fixture(),'2023-01-01','없는지역')['rows'],[])

    def test_dashboard_selection_persists_across_regions(self):
        app=AppTest.from_string("""
import streamlit as st
from tests.test_permit_trends import fixture
from ui_permit_trends import render_permit_trends
region=st.selectbox('지역',['중구','남구'])
render_permit_trends(fixture(),'2023-01-01',region)
""").run(timeout=30)
        self.assertFalse(app.exception)
        app.selectbox[1].select('의원·병원').run()
        self.assertFalse(app.exception)
        self.assertEqual([x.value for x in app.metric],['1건','1건','1건'])
        comparison=[d.value for d in app.dataframe if '지역' in d.value.columns][0]
        self.assertIn('지역 내 업종 비중(%)', comparison.columns)
        self.assertEqual(len(comparison), 1)
        app.selectbox[0].select('남구').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[1].value,'의원·병원')
        self.assertEqual([x.value for x in app.metric],['0건','0건','0건'])
        app.multiselect(key='dash_compare_regions').set_value([]).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('한 곳 이상' in i.value for i in app.info))

if __name__=='__main__':unittest.main()
