"""Synthetic failures; no API access or production data needed."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from staged_updates import collect_window

START, END = '2026-10-03T00:00:00', '2026-10-04T00:00:00'
K = ('3410000', 'synthetic-1', '일반음식점')


def values(name='old'):
    return dict(name=name, road_addr_raw='', jibun_addr_raw='', ld='2026-01-01', cd='', closed=False)


def row(n, when='2026-10-03T12:00:00', name='new'):
    return dict(key=('3410000',f'synthetic-{n}','일반음식점'), updated_at=when, values=values(name))


class StagedUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(scope=('3410000','일반음식점'),watermark=START,
                          records={K:dict(updated_at='2026-10-02T12:00:00',values=values())})
        self.batch = [row(1), row(2), row(3)]

    def fetch(self, page):
        return dict(page=page,total=len(self.batch),rows=deepcopy(self.batch[(page-1)*2:page*2]))

    def rejected_unchanged(self, fetch, **kwargs):
        before=deepcopy(self.state)
        with self.assertRaises((ValueError, TimeoutError)):
            collect_window(self.state,START,END,fetch,**kwargs)
        self.assertEqual(self.state,before)

    def test_complete_then_replay(self):
        before=deepcopy(self.state)
        first, counts=collect_window(self.state,START,END,self.fetch)
        self.assertEqual(counts,dict(inserted=2,updated=1,identical=0,stale=0))
        self.assertEqual(first['watermark'],END)
        second, counts=collect_window(first,START,END,self.fetch)
        self.assertEqual(first,second)
        self.assertEqual(counts['identical'],3)
        self.assertEqual(self.state,before)

    def test_second_page_timeout_then_retry(self):
        def fail(page):
            if page==2: raise TimeoutError('synthetic')
            return self.fetch(page)
        self.rejected_unchanged(fail)
        retried,_=collect_window(self.state,START,END,self.fetch)
        self.assertEqual(len(retried['records']),3)
        self.assertEqual(retried['watermark'],END)

    def test_stale_row_cannot_overwrite(self):
        self.state['records'][K]={'updated_at':'2026-10-03T18:00:00','values':values('latest')}
        new,stats=collect_window(self.state,START,END,self.fetch)
        self.assertEqual(new['records'][K],self.state['records'][K])
        self.assertEqual(stats['stale'],1)

    def test_same_timestamp_conflict(self):
        self.state['records'][K]['updated_at']=self.batch[0]['updated_at']
        self.rejected_unchanged(self.fetch)

    def test_total_changes(self):
        def fetch(page):
            result=self.fetch(page)
            if page==2: result['total']=4
            return result
        self.rejected_unchanged(fetch)

    def test_duplicate_across_pages(self):
        self.batch[-1]=deepcopy(self.batch[0])
        self.rejected_unchanged(self.fetch)

    def test_missing_second_page_rows(self):
        def fetch(page):
            result=self.fetch(page)
            if page==2: result['rows']=[]
            return result
        self.rejected_unchanged(fetch)

    def test_wrong_scope(self):
        self.batch[-1]['key']=('wrong','synthetic-3','일반음식점')
        self.rejected_unchanged(self.fetch)

    def test_end_boundary_excluded(self):
        self.batch[-1]['updated_at']=END
        self.rejected_unchanged(self.fetch)

    def test_empty_window_does_not_delete(self):
        self.batch=[]
        result,_=collect_window(self.state,START,END,self.fetch)
        self.assertEqual(result['records'],self.state['records'])
        self.assertEqual(result['watermark'],END)

    def test_gap_rejected(self):
        self.state['watermark']='2026-10-02T00:00:00'
        self.rejected_unchanged(self.fetch)

    def test_page_limit(self):
        self.rejected_unchanged(self.fetch,max_pages=1)

    def test_unknown_baseline_version(self):
        self.state['records'][K]['updated_at']=''
        self.rejected_unchanged(self.fetch)


if __name__=='__main__': unittest.main()
