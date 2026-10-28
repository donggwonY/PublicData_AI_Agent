import unittest
import pandas as pd
from pipeline.numeric import parse_area

class AreaParsingTest(unittest.TestCase):
    def test_thousands_and_original_index(self):
        x = pd.Series(['1,048.35', '2,251.30', '1,234,567.89'], index=[8,3,9])
        y = parse_area(x)
        self.assertEqual(y.index.tolist(), [8,3,9])
        self.assertEqual(y.tolist(), [1048.35,2251.3,1234567.89])

    def test_invalid_grouping_not_silently_repaired(self):
        y = parse_area(pd.Series(['1,04.35','12,34','1,234,','1,234m2',None,'']))
        self.assertTrue(y.isna().all())

    def test_plain_numbers_and_zero_preserved(self):
        y = parse_area(pd.Series(['53.04','.00',' 42.20 ',0,-5,None]))
        self.assertEqual(y.iloc[:5].tolist(),[53.04,0,42.2,0,-5])
        self.assertTrue(pd.isna(y.iloc[5]))

if __name__ == '__main__': unittest.main()
