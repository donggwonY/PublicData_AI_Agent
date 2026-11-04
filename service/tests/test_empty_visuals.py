import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from ui_visuals import metric_value, survival_chart, cycle_chart

class EmptyVisualsTest(unittest.TestCase):
    def test_empty_map_renders_message(self):
        app = AppTest.from_string("from ui_visuals import _map\n_map([], 'vacant_days', [], 'empty')")
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("좌표가 있는 결과가 없습니다", app.caption[0].value)

    def test_empty_rank_and_cycle_skip_plot(self):
        with patch('ui_visuals.st.caption') as caption, patch('ui_visuals.st.plotly_chart') as plot:
            survival_chart({'ranking_by_median_survival': [], 'basis': {}}, 'rank')
            cycle_chart({'yearly': []}, 'cycle')
            plot.assert_not_called()
            text=' '.join(str(c.args[0]) for c in caption.call_args_list)
            self.assertIn('최소 표본', text)
            self.assertIn('연도별 집계가 없습니다', text)

    def test_missing_is_distinct_from_zero(self):
        self.assertEqual(metric_value(None, '%'), '산출 불가')
        self.assertEqual(metric_value(float('nan'), '%'), '산출 불가')
        self.assertEqual(metric_value(0, '%'), '0%')
        self.assertEqual(metric_value(None, '년', '관찰기간 내 미도달'), '관찰기간 내 미도달')
