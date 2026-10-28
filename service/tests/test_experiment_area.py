import copy,json,tempfile,unittest
from pathlib import Path
from experiment_area import load_area
from streamlit.testing.v1 import AppTest

class AreaViewerTests(unittest.TestCase):
 def test_bad_cohort_and_bins_rejected(self):
  for mutate in [lambda x:x['scores']['sigmoid_rf'].update(n=1),lambda x:x['bins'][0].update(events=999),lambda x:x['scores']['sigmoid_rf'].update(predicted_pct=float('nan'))]:
   data=copy.deepcopy(load_area());mutate(data)
   with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'bad.json';path.write_text(json.dumps(data),encoding='utf-8')
    with self.assertRaises(ValueError):load_area(path)
 def test_default_latest_view_and_bin_switch(self):
  app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'experiment_app.py')).run(timeout=60)
  self.assertFalse(app.exception);self.assertEqual(app.metric[0].value,'1,608건');self.assertEqual(app.metric[2].value,'9.99%')
  self.assertEqual(len(app.dataframe[0].value),4);self.assertEqual(len(app.dataframe[1].value),4)
  app.selectbox[0].select('보정 전').run(timeout=60)
  self.assertFalse(app.exception);self.assertEqual(len(app.dataframe[1].value),3)
  self.assertTrue(any('0을 포함' in i.value for i in app.info))

if __name__=='__main__':unittest.main()
