"""Derive market probabilities from a score matrix, de-vig bookmaker prices, and settle bets."""
from __future__ import annotations

import math

import numpy as np


def rescale_to_1x2(m: np.ndarray, target: tuple[float, float, float]) -> np.ndarray:
    """Rescale a score matrix so its home/draw/away masses equal `target` (keeps the within-outcome
    score shape). Used to make all derived markets consistent with the ensemble 1X2."""
    n = m.shape[0]
    i, j = np.indices((n, n))
    out = m.copy()
    for mask, t in ((i > j, target[0]), (i == j, target[1]), (i < j, target[2])):
        s = out[mask].sum()
        if s > 0:
            out[mask] *= t / s
    return out / out.sum()


def ah_outcomes(m: np.ndarray, line: float) -> tuple[float, float, float, float]:
    """For a home Asian handicap `line` return (p_win, p_half_win, p_push, p_half_loss, ...) summarised as
    expected-return components: (p_full_win, p_half_win, p_push, p_half_loss); p_full_loss = remainder."""
    n = m.shape[0]
    i, j = np.indices((n, n))
    gd = (i - j).astype(float)
    halves = split_line(line)
    res = np.zeros_like(m)  # per-cell return multiplier on win part: 1=win, 0.5=half win, 0=push, -0.5 half loss, -1 loss
    for l in halves:
        r = gd + l
        res += np.where(r > 0, 1.0, np.where(r == 0, 0.0, -1.0)) / len(halves)
    p = lambda v: float(m[np.isclose(res, v)].sum())
    return p(1.0), p(0.5), p(0.0), p(-0.5)


def split_line(line: float) -> list[float]:
    """Quarter lines (e.g. -0.75) split into two half bets (-0.5, -1.0)."""
    if abs(line * 4) % 2 == 1:  # quarter line
        return [line - 0.25, line + 0.25]
    return [line]


def ah_ev(m: np.ndarray, line: float, price: float, side: str = "home") -> float:
    """Expected profit per unit stake for an Asian-handicap bet."""
    if side == "away":
        m = m.T
        line = -line
    n = m.shape[0]
    i, j = np.indices((n, n))
    gd = (i - j).astype(float)
    ev = np.zeros_like(m)
    for l in split_line(line):
        r = gd + l
        ev += np.where(r > 0, price - 1, np.where(r == 0, 0.0, -1.0)) / len(split_line(line))
    return float((m * ev).sum())


def ah_win_prob(m: np.ndarray, line: float, side: str = "home") -> float:
    """Probability-equivalent of an AH bet: P(win) + 0.5 P(half win) + 0.5 P(push) (for display)."""
    if side == "away":
        m, line = m.T, -line
    w, hw, push, hl = ah_outcomes(m, line)
    return w + 0.5 * hw + 0.5 * push


def markets_from_matrix(m: np.ndarray, ah_lines: list[float] | None = None) -> dict:
    n = m.shape[0]
    i, j = np.indices((n, n))
    tot = i + j
    ph, pd, pa = float(m[i > j].sum()), float(m[i == j].sum()), float(m[i < j].sum())
    out = {
        "1X2": {"home": ph, "draw": pd, "away": pa},
        "DC": {"1X": ph + pd, "12": ph + pa, "X2": pd + pa},
        "DNB": {"home": ph / (ph + pa), "away": pa / (ph + pa)},
        "BTTS": {"yes": float(m[(i > 0) & (j > 0)].sum()), "no": float(m[(i == 0) | (j == 0)].sum())},
    }
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        key = f"OU{str(line).replace('.', '')}"
        out[key] = {"over": float(m[tot > line].sum()), "under": float(m[tot < line].sum())}
    for line in (0.5, 1.5, 2.5):
        out[f"HOME_OU{str(line).replace('.', '')}"] = {"over": float(m[i > line].sum()), "under": float(m[i < line].sum())}
        out[f"AWAY_OU{str(line).replace('.', '')}"] = {"over": float(m[j > line].sum()), "under": float(m[j < line].sum())}
    flat = [((a, b), float(m[a, b])) for a in range(min(n, 7)) for b in range(min(n, 7))]
    flat.sort(key=lambda x: -x[1])
    out["CS_TOP"] = {f"{a}-{b}": p for (a, b), p in flat[:6]}
    for line in ah_lines or []:
        hw = ah_outcomes(m, line)
        aw = ah_outcomes(m.T, -line)
        out[f"AH{line:+g}"] = {"home_win": hw[0], "home_half_win": hw[1], "push": hw[2], "home_half_loss": hw[3],
                               "away_win": aw[0], "away_half_win": aw[1], "away_half_loss": aw[3]}
    return out


# ------------------------------------------------------------------ de-vig
def overround(prices: list[float]) -> float:
    return sum(1 / p for p in prices) - 1


def devig(prices: list[float], method: str = "power") -> list[float]:
    """Remove the bookmaker margin. 'power' (finds k with Σ(1/p)^k = 1) handles the favourite-longshot
    bias better than simple proportional normalisation; falls back to proportional."""
    inv = np.array([1 / p for p in prices], float)
    if method == "proportional" or len(prices) < 2:
        return list(inv / inv.sum())
    lo, hi = 0.5, 2.5
    for _ in range(60):
        k = (lo + hi) / 2
        s = np.sum(inv ** k)
        if s > 1:
            lo = k
        else:
            hi = k
    p = inv ** ((lo + hi) / 2)
    return list(p / p.sum())


# ------------------------------------------------------------------ settlement
def settle(market: str, selection: str, line: float | None, price: float, stake: float,
           hg: int, ag: int) -> tuple[str, float, str]:
    """Return (outcome, payout, rule). payout includes returned stake."""
    if market == "1X2":
        won = {"home": hg > ag, "draw": hg == ag, "away": hg < ag}[selection]
        return ("won", round(stake * price, 2), "1X2: 90 min + stoppage time result") if won else ("lost", 0.0, "1X2: 90 min result")
    if market == "OU25":
        tot = hg + ag
        won = tot > 2.5 if selection == "over" else tot < 2.5
        return ("won", round(stake * price, 2), "Total goals 2.5 (90 min)") if won else ("lost", 0.0, "Total goals 2.5 (90 min)")
    if market == "AH":
        gd = hg - ag if selection == "home" else ag - hg
        l = line if selection == "home" else -line
        halves = split_line(l)
        payout = 0.0
        for h in halves:
            r = gd + h
            part = stake / len(halves)
            payout += part * price if r > 0 else part if r == 0 else 0.0
        payout = round(payout, 2)
        full_win = round(stake * price, 2)
        if math.isclose(payout, full_win):
            outcome = "won"
        elif math.isclose(payout, stake):
            outcome = "void"  # push: stake returned
        elif payout == 0:
            outcome = "lost"
        elif payout > stake:
            outcome = "half_won"
        else:
            outcome = "half_lost"
        return outcome, payout, f"Asian handicap {l:+g} on {selection} (quarter lines split in two halves; push refunds)"
    raise ValueError(f"unsupported market {market}")


SETTLEMENT_RULES = {
    "general": "All markets settle on the result after 90 minutes plus stoppage time (extra time and penalties excluded). "
               "A bet settles only when the final score is verified by the results source(s) and no source conflicts. "
               "If sources conflict or no result is available the bet stays PENDING. Postponed matches: if a source "
               "reports the match postponed/cancelled and it is not played within 48 hours of the original kickoff the "
               "bet is VOID (stake refunded). Abandoned matches are VOID unless an official result is later reported.",
    "1X2": "Home / Draw / Away on the 90-minute result.",
    "OU25": "Over wins on 3+ total goals, Under on 0-2. No push possible.",
    "AH": "Asian handicap applied to the selected team's goal difference. Whole lines can push (stake refunded). "
          "Quarter lines (e.g. -0.75) are split into two equal half-stakes on the neighbouring lines (-0.5 and -1.0).",
}
