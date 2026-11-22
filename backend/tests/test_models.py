"""Unit tests: market maths, de-vig, settlement rules, Dixon-Coles, Elo."""
from datetime import datetime

import numpy as np
import pytest

from fil.models import dixon_coles as dc
from fil.models.elo import Elo, OrderedLogit
from fil.models.markets import (ah_ev, devig, markets_from_matrix, overround, rescale_to_1x2, settle, split_line)


def test_score_matrix_is_distribution():
    m = dc.score_matrix(1.6, 1.1, -0.08)
    assert m.min() >= 0
    assert abs(m.sum() - 1) < 1e-9


def test_markets_sum_to_one():
    mk = markets_from_matrix(dc.score_matrix(1.4, 1.2, -0.05), ah_lines=[-0.25])
    assert abs(sum(mk["1X2"].values()) - 1) < 1e-9
    assert abs(mk["OU25"]["over"] + mk["OU25"]["under"] - 1) < 1e-9
    assert abs(mk["BTTS"]["yes"] + mk["BTTS"]["no"] - 1) < 1e-9
    assert abs(sum(mk["DNB"].values()) - 1) < 1e-9
    ah = mk["AH-0.25"]
    assert 0 < ah["home_win"] < 1


def test_rescale_matches_target():
    m = rescale_to_1x2(dc.score_matrix(1.3, 1.3), (0.5, 0.2, 0.3))
    mk = markets_from_matrix(m)["1X2"]
    assert mk["home"] == pytest.approx(0.5) and mk["draw"] == pytest.approx(0.2) and mk["away"] == pytest.approx(0.3)


def test_devig_removes_margin():
    prices = [2.0, 3.4, 3.9]
    assert overround(prices) > 0
    for method in ("power", "proportional"):
        p = devig(prices, method)
        assert sum(p) == pytest.approx(1)
        assert all(a > b for a, b in zip([1 / x for x in prices], p))
    # power de-vig takes more margin off the longshot than proportional
    assert devig(prices, "power")[2] < devig(prices, "proportional")[2]


@pytest.mark.parametrize("sel,hg,ag,outcome,payout", [
    ("home", 2, 1, "won", 2.5), ("home", 1, 1, "lost", 0.0), ("draw", 0, 0, "won", 2.5), ("away", 0, 3, "won", 2.5),
])
def test_settle_1x2(sel, hg, ag, outcome, payout):
    assert settle("1X2", sel, None, 2.5, 1.0, hg, ag)[:2] == (outcome, payout)


def test_settle_ou():
    assert settle("OU25", "over", 2.5, 1.9, 1.0, 2, 1)[0] == "won"
    assert settle("OU25", "under", 2.5, 1.9, 1.0, 2, 1)[0] == "lost"
    assert settle("OU25", "under", 2.5, 1.9, 1.0, 1, 1)[:2] == ("won", 1.9)


def test_split_line():
    assert split_line(-0.75) == [-1.0, -0.5]
    assert split_line(-0.5) == [-0.5]
    assert split_line(0.25) == [0.0, 0.5]
    assert split_line(-1.0) == [-1.0]


@pytest.mark.parametrize("sel,line,hg,ag,outcome,payout", [
    ("home", -0.5, 1, 0, "won", 2.0),
    ("home", -1.0, 1, 0, "void", 1.0),        # push
    ("home", -0.75, 1, 0, "half_won", 1.5),   # half push (-1.0) + half win (-0.5)
    ("home", -0.25, 0, 0, "half_lost", 0.5),  # half push (0) + half loss (-0.5)
    ("away", -0.25, 0, 0, "half_won", 1.5),   # away +0.25: half push + half win
    ("away", 0.5, 1, 1, "lost", 0.0),         # away -0.5 on a draw
    ("home", 0.0, 2, 2, "void", 1.0),
])
def test_settle_asian_handicap(sel, line, hg, ag, outcome, payout):
    o, p, _ = settle("AH", sel, line, 2.0, 1.0, hg, ag)
    assert (o, p) == (outcome, payout)


def test_ah_ev_consistent_with_settlement():
    m = dc.score_matrix(1.5, 1.0, 0)
    n = m.shape[0]
    for line in (-0.75, -0.5, -0.25, 0.0, 0.25):
        for side in ("home", "away"):
            exp = sum(m[i, j] * (settle("AH", side, line, 1.95, 1.0, i, j)[1] - 1) for i in range(n) for j in range(n))
            assert ah_ev(m, line, 1.95, side) == pytest.approx(exp, abs=0.006)  # settlement rounds to cents


def test_dixon_coles_gradient_matches_numeric():
    rng = np.random.default_rng(0)
    n, T = 200, 6
    hi, ai = rng.integers(0, T, n), rng.integers(0, T, n)
    ai = np.where(ai == hi, (ai + 1) % T, ai)
    hg, ag = rng.poisson(1.4, n), rng.poisson(1.1, n)
    days = rng.uniform(0, 600, n)
    from scipy.optimize import check_grad

    def f(p):
        return _negll(p, hi, ai, hg, ag, days, T)[0]

    def g(p):
        return _negll(p, hi, ai, hg, ag, days, T)[1]

    p0 = np.concatenate([rng.normal(0, 0.2, 2 * T), [0.2, 0.25, -0.05]])
    assert check_grad(f, g, p0) < 1e-3 * max(1, np.linalg.norm(g(p0)))


def _negll(p, hi, ai, hg, ag, days, T):
    captured = {}

    def fake_minimize(fun, x0, **kw):
        captured["v"] = fun(p)

        class R:
            x, success = x0, True
        return R()

    import fil.models.dixon_coles as mod
    orig = mod.minimize
    mod.minimize = fake_minimize
    try:
        mod.fit(hi, ai, hg, ag, days, T)
    finally:
        mod.minimize = orig
    return captured["v"]


def test_dixon_coles_recovers_strengths():
    from tests.conftest import synthetic_league

    recs, att, dfn = synthetic_league(n_teams=12, seasons=3, with_odds=False)
    matches = [dict(home_id=int(r.home.split()[1]), away_id=int(r.away.split()[1]), hg=r.home_goals, ag=r.away_goals,
                    kickoff=r.kickoff_utc) for r in recs]
    p = dc.fit_competition(matches, datetime(2026, 11, 2), ridge=0.5, use_xg=False)
    assert p.converged
    est = dict(zip(p.teams, p.att))
    corr = np.corrcoef([est[i] for i in range(12)], att)[0, 1]
    assert corr > 0.8
    assert 0.1 < p.home < 0.45  # true home advantage 0.25


def test_elo_and_ordered_logit():
    e = Elo()
    for _ in range(30):
        e.update("A", "B", 3, 0, "ENG1")
    assert e.ratings["A"] > e.ratings["B"]
    ol = OrderedLogit()
    pr = ol.probs([0.0, 1.0, -1.0])
    assert np.allclose(pr.sum(axis=1), 1)
    assert pr[1, 0] > pr[0, 0] > pr[2, 0]
    x = np.random.default_rng(1).normal(0, 0.5, 3000)
    y = np.where(x + np.random.default_rng(2).logistic(0, 0.5, 3000) > 0.3, 0, np.where(x > -0.6, 1, 2))
    ol.fit(x, y)
    assert ol.beta > 0 and ol.th1 < ol.th2
