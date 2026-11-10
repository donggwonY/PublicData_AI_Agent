import copy
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
from prediction_review_app import load_results,review_cell

class ReviewTests(unittest.TestCase):
    def test_known_large_error_is_held(self):
        w=load_results()['windows'][-1]
        c=next(r for r in w['regions'] if r['industry']=='담배소매업' and r['gu']=='남구')
        self.assertIn('평균 예측 오차 5%p 초과',review_cell(c))
    def test_missing_auc_and_small_sample_are_explicit(self):
        c=copy.deepcopy(load_results()['windows'][-1]['regions'][0])
        c['scores']['region_cal'].update(n=10,events=1,roc_auc=None)
        self.assertIn('검증 표본 부족',review_cell(c))
        self.assertIn('폐업 여부 구분 능력 부족',review_cell(c))
    def test_filter_displays_historical_years(self):
        a=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'prediction_review_app.py')).run(timeout=60)
        a.selectbox[0].select('담배소매업').run(timeout=60)
        a.selectbox(key='review_gu').select('남구').run(timeout=60)
        self.assertFalse(a.exception)
        table=a.dataframe[0].value
        self.assertEqual(table['연도'].tolist(),list(range(2013,2026)))
        self.assertIn('평균 예측 오차 5%p 초과',table.iloc[-1]['검토 결과'])

class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        cls.model=json.loads((Path(__file__).resolve().parents[1]/'data/research/closure_preview_model.json').read_text(encoding='utf-8'))
    def test_blocked_cell_never_returns_number(self):
        from core.prediction_preview import preview
        r=preview(self.model,'담배소매업','남구','1-3')
        self.assertIsNone(r['probability'])
        self.assertIn('평균 예측 오차 5%p 초과',r['reasons'])
    def test_unknown_input_is_not_silently_predicted(self):
        from core.prediction_preview import preview
        self.assertIsNone(preview(self.model,'미등록업종','중구','1-3')['probability'])
    def test_supported_input_and_blocked_ui(self):
        from core.prediction_preview import preview
        r=preview(self.model,'미용업','중구','1-3')
        self.assertIsNotNone(r['probability'])
        self.assertTrue(0<r['probability']<1)
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'prediction_review_app.py')).run(timeout=60)
        app.selectbox[0].select('담배소매업').run(timeout=60)
        app.selectbox(key='review_gu').select('남구').run(timeout=60)
        app.button(key='preview_calculate').click().run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(any('표시 보류' in x.value for x in app.warning))
        self.assertEqual(len(app.metric),0)
