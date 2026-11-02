import math
import unittest
import pandas as pd
from ui_visuals import _map_view

class MapViewTest(unittest.TestCase):
    def test_neighborhood_fits_narrow_chat(self):
        df = pd.DataFrame({"lat": [35.875, 35.881], "lon": [128.625, 128.633]})
        view = _map_view(df)
        self.assertGreater(view.zoom, 14)
        self.assertLessEqual(view.zoom, 16)
        self.assertAlmostEqual(view.longitude, 128.629)
        width = (df.lon.max() - df.lon.min()) / 360 * 512 * 2 ** view.zoom
        self.assertLessEqual(width, 256.0001)

    def test_city_is_not_cropped_to_neighborhood(self):
        view = _map_view(pd.DataFrame({"lat": [35.7, 36.0], "lon": [128.4, 128.8]}))
        self.assertLess(view.zoom, 11)

    def test_single_and_duplicate_points_have_finite_zoom(self):
        for count in [1, 3]:
            view = _map_view(pd.DataFrame({"lat": [35.88]*count, "lon": [128.63]*count}))
            self.assertEqual(view.zoom, 16)
            self.assertTrue(math.isfinite(view.latitude))

    def test_reset_button_rerenders_without_error(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string("""
from ui_visuals import _map
_map([{'address':'A','lat':35.875,'lon':128.625,'vacant_days':10},
      {'address':'B','lat':35.881,'lon':128.633,'vacant_days':20}],
     'vacant_days', ['vacant_days'], 'test_map')
""")
        app.run()
        self.assertFalse(app.exception)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['test_map_view_reset'], 1)
