"""배치 규칙 검사: 겸업 묶기와 추출 시점 이후 날짜 처리 (2026-11-08 추가)."""
import unittest

import pandas as pd

from pipeline.build import clean, flag_short_events, max_concurrency, merge_concurrent_licenses

REF = pd.Timestamp("2026-11-06")
T = pd.Timestamp


def _stores(rows):
    df = pd.DataFrame(rows, columns=["uid", "service", "name", "ld", "cd", "closed"])
    df["ld"], df["cd"] = pd.to_datetime(df["ld"]), pd.to_datetime(df["cd"])
    df["end"] = df["cd"].where(df["closed"], REF)
    df["dur_days"] = (df["end"] - df["ld"]).dt.days
    df["category"] = df["service"]
    return df


class BuildRulesTest(unittest.TestCase):
    def test_same_unit_overlap_same_name_is_one_store(self):
        st = _stores([
            ("A 1층", "약국", "행복 약국", "2015-01-01", None, False),
            ("A 1층", "동물약국", "행복약국", "2018-03-01", None, False),
        ])
        stores, occ = merge_concurrent_licenses(st, REF)
        assert len(stores) == 2 and stores["occupant_id"].nunique() == 1
        assert len(occ) == 1
        row = occ.iloc[0]
        assert row["service"] == "약국"          # config.SERVICES 순서가 빠른 업종이 대표
        assert row["ld"] == T("2015-01-01") and not row["closed"] and row["n_licenses"] == 2
        # 묶기 전에는 동시영업 2 → 다점포 오판, 묶은 뒤에는 1
        assert max_concurrency(st, REF, 60).iloc[0] == 2
        assert max_concurrency(occ, REF, 60).iloc[0] == 1


    def test_not_merged_when_name_differs_or_no_overlap(self):
        st = _stores([
            ("A 1층", "일반음식점", "김밥천국", "2010-01-01", "2012-01-01", True),
            ("A 1층", "일반음식점", "김밥천국", "2013-05-01", None, False),   # 같은 상호지만 기간이 안 겹침
            ("A 1층", "즉석판매제조가공업", "반찬나라", "2014-01-01", None, False),  # 기간은 겹치지만 상호가 다름
            ("B 1층", "약국", "김밥천국", "2014-01-01", None, False),        # 다른 자리
        ])
        _, occ = merge_concurrent_licenses(st, REF)
        assert len(occ) == 4


    def test_occupant_closed_only_when_all_licenses_closed(self):
        st = _stores([
            ("A 1층", "휴게음식점", "카페 모아", "2019-01-01", "2024-06-30", True),
            ("A 1층", "즉석판매제조가공업", "카페모아", "2020-01-01", "2025-02-01", True),
            ("C 1층", "휴게음식점", "빵집", "2019-01-01", "2024-06-30", True),
            ("C 1층", "제과점영업", "빵집", "2020-01-01", None, False),
        ])
        _, occ = merge_concurrent_licenses(st, REF)
        a = occ[occ["uid"] == "A 1층"].iloc[0]
        c = occ[occ["uid"] == "C 1층"].iloc[0]
        assert a["closed"] and a["cd"] == T("2025-02-01") and a["service"] == "휴게음식점"
        assert not c["closed"] and pd.isna(c["cd"])


    def test_empty_name_never_merged(self):
        st = _stores([
            ("A 1층", "약국", "", "2015-01-01", None, False),
            ("A 1층", "동물약국", "", "2016-01-01", None, False),
        ])
        _, occ = merge_concurrent_licenses(st, REF)
        assert len(occ) == 2


    def test_dates_after_extraction_are_dropped(self):
        base = {"개방자치단체코드": "1", "인허가취소일자": None, "소재지면적": None, "업태구분명": None,
                "위생업태명": None, "사업장명": "x", "service": "미용업",
                "지번주소": "대구광역시 중구 삼덕동1가 1", "도로명주소": None,
                "최종수정시점": "2026-11-06 10:00:00", "데이터갱신시점": "2026-11-06 10:00:00"}
        df = pd.DataFrame([
            base | {"관리번호": "1", "인허가일자": "2020-01-01", "영업상태명": "폐업", "폐업일자": "2026-11-23"},
            base | {"관리번호": "2", "인허가일자": "2020-01-01", "영업상태명": "영업/정상", "폐업일자": None},
            base | {"관리번호": "3", "인허가일자": "2021-01-01", "영업상태명": "폐업", "폐업일자": "2026-11-05"},
        ])
        quality = {}
        out, ref = clean(df, quality)
        assert ref == T("2026-11-05")                       # 미래 폐업일이 기준일을 밀지 않음
        assert quality["date_after_extraction"]["close"] == 1
        assert set(out["관리번호"]) == {"2", "3"}            # 폐업일이 지워진 폐업 행은 제외

    def test_non_storefront_categories_dropped(self):
        base = {"개방자치단체코드": "1", "인허가취소일자": None, "소재지면적": None, "위생업태명": None,
                "사업장명": "x", "service": "건강기능식품일반판매업", "영업상태명": "영업/정상", "폐업일자": None,
                "지번주소": "대구광역시 중구 삼덕동1가 1", "도로명주소": None, "인허가일자": "2020-01-01",
                "최종수정시점": "2026-11-06 10:00:00", "데이터갱신시점": "2026-11-06 10:00:00"}
        df = pd.DataFrame([base | {"관리번호": "1", "업태구분명": "영업장판매"},
                           base | {"관리번호": "2", "업태구분명": "전자상거래(통신판매업)"},
                           base | {"관리번호": "3", "업태구분명": "방문판매"},
                           base | {"관리번호": "4", "업태구분명": "전자상거래(통신판매업)", "service": "미용업"}])
        quality = {}
        out, _ = clean(df, quality)
        assert set(out["관리번호"]) == {"1", "4"}            # 다른 업종은 같은 업태명이어도 유지
        assert quality["non_storefront_excluded"]["건강기능식품일반판매업"] == 2

    def test_short_event_only_in_multi_unit_and_within_30_days(self):
        st = _stores([
            ("백화점 지하1층", "즉석판매제조가공업", "행사A", "2024-01-01", "2024-01-10", True),   # 다점포·9일 → 행사
            ("백화점 지하1층", "즉석판매제조가공업", "행사B", "2024-01-05", "2024-03-01", True),   # 다점포·56일 → 아님
            ("단독 1층", "일반음식점", "단명식당", "2024-01-01", "2024-01-20", True),             # 단독 자리 → 아님
        ])
        stores, occ = merge_concurrent_licenses(st, REF)
        units = pd.DataFrame({"uid": ["백화점 지하1층", "단독 1층"], "is_single_unit": [False, True]})
        occ, stores = flag_short_events(occ, stores, units)
        got = dict(zip(occ["name"], occ["short_event"]))
        assert got == {"행사A": True, "행사B": False, "단명식당": False}
        assert stores["short_event"].sum() == 1


if __name__ == "__main__":
    unittest.main()
