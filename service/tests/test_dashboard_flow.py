"""Main dashboard navigation and filter scope regression using local snapshot."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

class DashboardFlowTests(unittest.TestCase):
    def test_explore_scope_and_secondary_views(self):
        with patch.dict(os.environ, {'APP_DATA_SOURCE':'parquet'}):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=90)
            self.assertFalse(app.exception)
            self.assertEqual(app.tabs[0].label,'📊 상권 둘러보기')
            self.assertEqual(len(app.tabs),3)
            app.selectbox(key='dash_trend_industry').select('동물미용업').run(timeout=90)
            self.assertFalse(app.exception)
            comparison=[d.value for d in app.dataframe if '지역' in d.value.columns]
            self.assertEqual(len(comparison),1)
            self.assertLessEqual(len(comparison[0]),4)
            app.selectbox(key='dash_gu').select('군위군').run(timeout=90)
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='dash_trend_industry').value,'동물미용업')
            app.radio(key='dash_view').set_value('상세 통계').run(timeout=90)
            self.assertFalse(app.exception)
            self.assertTrue(any('전체 업종 기준' in x.value for x in app.caption))
            app.radio(key='dash_view').set_value('동네·자리').run(timeout=90)
            self.assertFalse(app.exception)
            app.radio(key='dash_view').set_value('업종 비교').run(timeout=90)
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='dash_trend_industry').value,'동물미용업')
