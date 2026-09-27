"""Confidence bands must not claim more than their cases can support.

The overview used to print "< 0.5 → 100%" off four cases, above the
≥ 0.85 band, under a caption asserting calibration. These pin what a
band is allowed to say.
"""

from src.overview_service import MIN_BAND_CASES, _bucket_cases


def _case(p: float, accurate: bool) -> dict:
    return {"top": {"$p": p, "$value": "x"}, "accurate": accurate}


def test_an_empty_band_has_no_accuracy_rather_than_zero():
    bands = _bucket_cases([_case(0.9, True)] * 30)
    empty = [b for b in bands if b.count == 0]
    assert empty and all(b.accuracy is None for b in empty)
    assert all(b.mean_p is None for b in empty)


def test_a_band_with_few_cases_is_marked_thin():
    cases = [_case(0.9, True)] * 30 + [_case(0.3, True)] * 4
    low = next(b for b in _bucket_cases(cases) if b.min_p == 0.0)
    assert low.count == 4 < MIN_BAND_CASES
    assert low.thin
    high = next(b for b in _bucket_cases(cases) if b.min_p == 0.85)
    assert not high.thin


def test_each_band_reports_the_confidence_it_is_judged_against():
    cases = [_case(0.9, True)] * 20 + [_case(0.95, False)] * 20
    high = next(b for b in _bucket_cases(cases) if b.min_p == 0.85)
    assert high.accuracy == 0.5
    assert high.mean_p == 0.925


def test_band_edges_are_half_open():
    cases = [_case(0.85, True), _case(0.5, True), _case(0.4999, True)]
    by_min = {b.min_p: b.count for b in _bucket_cases(cases)}
    assert by_min == {0.85: 1, 0.5: 1, 0.0: 1}
