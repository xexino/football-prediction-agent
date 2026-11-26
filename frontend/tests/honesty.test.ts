import { test } from "node:test";
import assert from "node:assert/strict";
import { legacyStake, liveScoreText } from "../src/lib/honesty.ts";

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
