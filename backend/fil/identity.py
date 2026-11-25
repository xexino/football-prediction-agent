"""Team identity migration for UEFA competitions — DRY RUN ONLY (model council 2026-11-25, roadmap D-02).

UEFA cup fixtures were ingested with teams whose country is "Europe", so e.g. "Arsenal" in the Champions League
is a different team id from "Arsenal" in the Premier League. Those clubs therefore have no domestic history in
the cups (Engine A makes no UEFA predictions) and their rest-day/form counts are split.

This module only PROPOSES a reversible alias map and reports its effect. Nothing is written. A later, separate
step may apply it — only after a domestic re-backtest — through a `team_merges` journal table:

    team_merges(id, from_team_id, to_team_id, method, confidence, applied_at, reverted_at,
                repointed_fixtures JSON  -- [(fixture_id, "home"|"away"), ...])

Apply = re-point the listed fixture columns + add TeamAlias rows; revert = re-point exactly those fixture columns
back and delete the added aliases. Immutable tables (predictions, bets, settlements) reference fixtures, not teams,
so neither step touches an audit record.

    python -m fil identity-dry-run OUT.md [--json OUT.json]
"""
from __future__ import annotations

import difflib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from .config import settings
from .teamnames import normalize

# Hand-checked names UEFA feeds use that differ from the domestic feed (football-data.co.uk) spelling.
# Each entry must be reviewed by a person before any apply step; the dry run reports them as "curated".
CURATED = {
    "atleti": "ath madrid", "atletico madrid": "ath madrid", "athletic club": "ath bilbao", "inter": "inter",
    "internazionale": "inter", "man city": "man city", "manchester city": "man city",
    "manchester united": "man united", "psg": "paris sg", "paris saint germain": "paris sg",
    "bayern munchen": "bayern munich", "fc bayern munchen": "bayern munich", "borussia dortmund": "dortmund",
    "bayer leverkusen": "leverkusen", "bayer 04 leverkusen": "leverkusen", "rb leipzig": "rb leipzig",
    "eintracht frankfurt": "ein frankfurt", "vfb stuttgart": "stuttgart", "psv": "psv eindhoven",
    "sporting cp": "sp lisbon", "sporting": "sp lisbon", "benfica": "benfica", "fc porto": "porto",
    "club brugge": "club brugge", "olympique marseille": "marseille", "as monaco": "monaco",
    "losc lille": "lille", "ss lazio": "lazio", "as roma": "roma", "ac milan": "milan",
    "real sociedad": "sociedad", "real betis": "betis", "celta vigo": "celta", "fc barcelona": "barcelona",
    "barca": "barcelona", "tottenham hotspur": "tottenham", "newcastle united": "newcastle",
    "nottingham forest": "nott m forest", "aston villa": "aston villa", "como 1907": "como",
    "bayern": "bayern munich", "kobenhavn": "copenhagen", "kbenhavn": "copenhagen",
    "red bull salzburg": "salzburg", "fc salzburg": "salzburg",
}
FUZZY_MIN = 0.92          # only near-identical spellings are proposed automatically
NATIONAL_COMPS = ("UNL", "WCQ", "INTFR", "EC", "WC", "ECQ", "AFCON", "COPA")


def _conn(db_path=None):
    return sqlite3.connect(f"file:{db_path or settings.db_path}?mode=ro", uri=True)


def propose(db_path=None) -> dict:
    con = _conn(db_path)
    teams = {tid: (name, country, bool(nat)) for tid, name, country, nat in
             con.execute("SELECT id, name, country, is_national FROM teams")}
    europe = {tid: t for tid, t in teams.items() if t[1] == "Europe"}
    domestic = {tid: t for tid, t in teams.items() if t[1] not in ("Europe", "") and not t[2]}
    by_norm = defaultdict(set)
    for tid, (name, _c, _n) in domestic.items():
        by_norm[normalize(name)].add(tid)
    for alias, tid in con.execute("SELECT alias_norm, team_id FROM team_aliases"):
        if tid in domestic:
            by_norm[alias].add(tid)
    # domestic teams that play in a domestic league (have >= 10 league fixtures): avoids matching youth/women sides
    league_n = defaultdict(int)
    for tid, n in con.execute("SELECT t, COUNT(*) FROM (SELECT home_team_id t FROM fixtures f JOIN competitions c ON "
                              "c.id=f.competition_id WHERE substr(c.code, -1) BETWEEN '0' AND '9' UNION ALL SELECT "
                              "away_team_id FROM fixtures f JOIN competitions c ON c.id=f.competition_id WHERE "
                              "substr(c.code, -1) BETWEEN '0' AND '9') GROUP BY t"):
        league_n[tid] = n
    fx_count = defaultdict(int)
    for tid, n in con.execute("SELECT t, COUNT(*) FROM (SELECT home_team_id t FROM fixtures UNION ALL "
                              "SELECT away_team_id FROM fixtures) GROUP BY t"):
        fx_count[tid] = n

    proposals, unmatched, ambiguous = [], [], []
    norms = list(by_norm)
    for eid, (name, _c, _n) in sorted(europe.items(), key=lambda x: x[1][0]):
        n = normalize(name)
        method, cands, score = None, set(), 1.0
        if n in by_norm:
            method, cands = "exact", by_norm[n]
        elif n in CURATED and CURATED[n] in by_norm:
            method, cands = "curated", by_norm[CURATED[n]]
        else:
            best = difflib.get_close_matches(n, norms, n=2, cutoff=FUZZY_MIN)
            if best:
                method, cands = "fuzzy", by_norm[best[0]]
                score = difflib.SequenceMatcher(None, n, best[0]).ratio()
        cands = {c for c in cands if league_n.get(c, 0) >= 10}
        if not cands:
            unmatched.append({"europe_id": eid, "name": name, "fixtures": fx_count[eid]})
            continue
        if len(cands) > 1:
            ambiguous.append({"europe_id": eid, "name": name, "candidates": sorted(cands)})
            continue
        did = cands.pop()
        proposals.append({"europe_id": eid, "name": name, "domestic_id": did, "domestic_name": teams[did][0],
                          "country": teams[did][1], "method": method, "confidence": round(score, 3),
                          "fixtures_repointed": fx_count[eid], "domestic_league_fixtures": league_n[did]})

    # conflicts: two Europe ids -> same domestic id, or a merged team playing twice on one date
    tgt = defaultdict(list)
    for p in proposals:
        tgt[p["domestic_id"]].append(p["europe_id"])
    multi = {d: e for d, e in tgt.items() if len(e) > 1}
    remap = {p["europe_id"]: p["domestic_id"] for p in proposals}
    dates = defaultdict(list)
    for fid, h, a, md in con.execute("SELECT id, home_team_id, away_team_id, match_date FROM fixtures"):
        for t in (h, a):
            dates[(remap.get(t, t), md)].append(fid)
    clashes = [{"team_id": t, "date": d, "fixtures": f} for (t, d), f in dates.items()
               if len(f) > 1 and any(x in remap.values() for x in [t])]
    # club vs national entity sharing one id (e.g. "Andorra" = FC Andorra and the national team)
    mixed = []
    for tid, name, clubs, nats in con.execute(
            "SELECT t.id, t.name, SUM(substr(c.code,-1) BETWEEN '0' AND '9'), SUM(c.code IN (%s)) FROM teams t "
            "JOIN fixtures f ON t.id IN (f.home_team_id, f.away_team_id) JOIN competitions c ON c.id=f.competition_id "
            "GROUP BY t.id HAVING SUM(substr(c.code,-1) BETWEEN '0' AND '9') > 0 AND SUM(c.code IN (%s)) > 0"
            % ((",".join(f"'{c}'" for c in NATIONAL_COMPS),) * 2)):
        mixed.append({"team_id": tid, "name": name, "club_fixtures": clubs, "national_fixtures": nats})
    amb_alias = [{"alias": a, "source": src, "team_ids": ids} for a, src, ids in (
        (a, src, sorted({int(x) for x in ids.split(",")})) for a, src, ids in con.execute(
            "SELECT alias_norm, source, GROUP_CONCAT(DISTINCT team_id) FROM team_aliases GROUP BY alias_norm, source "
            "HAVING COUNT(DISTINCT team_id) > 1"))]
    con.close()
    return {"ambiguous_aliases": amb_alias, "europe_teams": len(europe), "proposals": proposals, "ambiguous": ambiguous, "unmatched": unmatched,
            "conflicts_same_target": [{"domestic_id": d, "europe_ids": e} for d, e in multi.items()],
            "date_clashes_after_merge": clashes[:50], "club_national_mixed": mixed}


def report_md(r: dict) -> str:
    by = defaultdict(int)
    for p in r["proposals"]:
        by[p["method"]] += 1
    L = ["# UEFA team identity — dry-run report (nothing applied)", "",
         f"* \"Europe\" teams: **{r['europe_teams']}**",
         f"* Proposed merges: **{len(r['proposals'])}** ({', '.join(f'{k} {v}' for k, v in sorted(by.items()))})",
         f"* Fixture columns that would be re-pointed: **{sum(p['fixtures_repointed'] for p in r['proposals'])}**",
         f"* Ambiguous (several domestic candidates, never merged automatically): **{len(r['ambiguous'])}**",
         f"* Unmatched (no domestic twin in our leagues — clubs from countries we don't cover): **{len(r['unmatched'])}**",
         f"* Conflicts — two Europe ids onto one domestic id: **{len(r['conflicts_same_target'])}**; "
         f"same team twice on one date after merge: **{len(r['date_clashes_after_merge'])}**",
         f"* Club/national entities sharing one id: **{len(r['club_national_mixed'])}**", "",
         "Apply only after: (1) a person reviews every `curated`/`fuzzy` row, (2) a domestic walk-forward re-backtest "
         "with the merged ids shows no regression, (3) a UEFA prediction path exists (Engine A fits Dixon-Coles only "
         "for domestic leagues). The merge is journaled in `team_merges` and fully reversible.", "",
         "## Proposed merges", "", "| Europe id | UEFA name | → domestic id | Domestic name | Country | Method | Conf. | Fixtures |",
         "|---|---|---|---|---|---|---|---|"]
    for p in r["proposals"]:
        L.append(f"| {p['europe_id']} | {p['name']} | {p['domestic_id']} | {p['domestic_name']} | {p['country']} | "
                 f"{p['method']} | {p['confidence']} | {p['fixtures_repointed']} |")
    for title, key, cols in (("Ambiguous", "ambiguous", ("europe_id", "name", "candidates")),
                             ("Conflicts (same target)", "conflicts_same_target", ("domestic_id", "europe_ids")),
                             ("Date clashes after merge", "date_clashes_after_merge", ("team_id", "date", "fixtures")),
                             ("Club/national mixed ids", "club_national_mixed", ("team_id", "name", "club_fixtures", "national_fixtures")),
                             ("Unmatched", "unmatched", ("europe_id", "name", "fixtures")),
                             ("Ambiguous aliases (one spelling -> several teams; never used to resolve, teamnames.py)",
                              "ambiguous_aliases", ("alias", "source", "team_ids"))):
        L += ["", f"## {title} ({len(r[key])})", ""]
        if r[key]:
            L += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            L += ["| " + " | ".join(str(x[c]) for c in cols) + " |" for x in r[key]]
        else:
            L.append("none")
    return "\n".join(L) + "\n"


def dry_run(out_md: Path, out_json: Path | None = None, db_path=None) -> dict:
    r = propose(db_path)
    Path(out_md).write_text(report_md(r))
    if out_json:
        Path(out_json).write_text(json.dumps(r, indent=1))
    return r
