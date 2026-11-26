import { test } from "node:test";
import assert from "node:assert/strict";
import { matchState } from "../src/lib/matchState.ts";

// ui.tsx statusNow/awaitingResult are thin wrappers over matchState; the table below is the behaviour every page
// now shares (council cycle 2026-11-26 06:50: three helpers disagreed for the same match).
const KO = "2026-11-26T20:00:00Z";
const at = (h: number) => new Date(KO).getTime() + h * 3.6e6;
test("1 h after kickoff, any snapshot phase without a feed → live", () => {
  for (const ph of [undefined, "upcoming", "awaiting_result"]) assert.equal(matchState(KO, ph, at(1)), "live");
});
test("finished without score is awaiting, never 'in play' forever", () => assert.equal(matchState(KO, "finished", at(30)), "awaiting"));
test("a frozen 'live' phase ends after 3 h", () => assert.equal(matchState(KO, "live", at(5)), "awaiting"));
test("postponed stays postponed", () => assert.equal(matchState(KO, "postponed", at(1)), "postponed"));
