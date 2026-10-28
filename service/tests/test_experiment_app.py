"""Evidence viewer checks: same cohort and interactive window selection."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from experiment_app import load_results
from streamlit.testing.v1 import AppTest


class ExperimentTests(unittest.TestCase):
    def test_rejects_different_cohort(self):
        data=copy.deepcopy(load_results())
        data['results'][0]['scores']['context']['n'] += 1
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json';path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError): load_results(path)

    def test_rejects_inconsistent_rate(self):
        data=copy.deepcopy(load_results())
        data['results'][0]['scores']['base']['actual_pct']=99
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json';path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError): load_results(path)

    def test_period_switch_matches_saved_result(self):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'experiment_app.py')).run(timeout=60)
        app.radio[0].set_value('초기 주변 상권').run(timeout=60)
        self.assertFalse(app.exception)
        for row in load_results()['results']:
            app.selectbox[0].select(row['window']).run(timeout=60)
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value,f"{row['scores']['base']['n']:,}건")
            self.assertEqual(app.metric[1].value,f"{row['scores']['base']['actual_pct']:.2f}%")
            self.assertEqual(len(app.dataframe[0].value),3)

if __name__=='__main__': unittest.main()
