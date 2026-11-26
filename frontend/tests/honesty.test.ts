import { test } from "node:test";
import assert from "node:assert/strict";
import { healthCauses, keepOnToday, legacyStake, liveScoreText, sampleNote, smallSample } from "../src/lib/honesty.ts";

test("bets before the €10 rule are legacy", () => {
  assert.equal(legacyStake("2026-11-24T19:31:44"), true);
  assert.equal(legacyStake("2026-11-25T21:20:59Z"), true);
  assert.equal(legacyStake("2026-11-25T21:21:00Z"), false);
  assert.equal(legacyStake("2026-11-26T10:00:00+00:00"), false);
  assert.equal(legacyStake(null), false);
});
test("a live score older than 20 min is not presented as current", () => {
  assert.equal(liveScoreText("0-0", 12), "0-0 (delayed score, 12 min old)");
  assert.equal(liveScoreText("0-0", 106), "last score seen 0-0, 106 min ago (no newer update yet)");
});
test("headline percentages need a minimum sample", () => {
  assert.equal(smallSample(1), true);
  assert.equal(smallSample(19), true);
  assert.equal(smallSample(20), false);
  assert.equal(smallSample(undefined), true);
  assert.equal(sampleNote(1), "1 settled bet: not meaningful yet (needs 20+)");
});
test("a started unscored match stays on today's list for 12 h", () => {
  const ko = "2026-11-26T20:00:00Z", t = (h: number) => new Date(ko).getTime() + h * 3.6e6;
  assert.equal(keepOnToday(false, ko, null, undefined, t(3.5)), true);   // 23:30Z = 00:30 Rome next day
  assert.equal(keepOnToday(false, ko, "2-1", undefined, t(3.5)), false); // finished with a score: normal day rule
  assert.equal(keepOnToday(false, ko, null, undefined, t(13)), false);
  assert.equal(keepOnToday(false, ko, null, undefined, t(-1)), false);
  assert.equal(keepOnToday(false, ko, null, "postponed", t(3.5)), false); // never keeps a postponed match
  assert.equal(keepOnToday(true, ko, "2-1", undefined, t(1)), true);
});
test("health banner names its causes", () => {
  assert.equal(healthCauses({ results: { state: "STALE", overdue: 18 }, live: { state: "DEGRADED" }, odds: { state: "HEALTHY" } }),
    "results (18 overdue), live");
  assert.equal(healthCauses(null), "");
});
