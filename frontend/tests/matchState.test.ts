import { test } from "node:test";
import assert from "node:assert/strict";
import { matchState } from "../src/lib/matchState.ts";

const KO = "2026-11-25T18:00:00Z";
const at = (h: number) => new Date(KO).getTime() + h * 3.6e6;

test("before kickoff", () => assert.equal(matchState(KO, "upcoming", at(-1)), "upcoming"));
test("no phase, 52 minutes in → live (not finished)", () => assert.equal(matchState(KO, undefined, at(0.87)), "live"));
test("backend says awaiting_result mid-match → still live", () => assert.equal(matchState(KO, "awaiting_result", at(1)), "live"));
test("after 2.5 h → awaiting", () => assert.equal(matchState(KO, "awaiting_result", at(3)), "awaiting"));
test("stale live phase stops after 3 h", () => {
  assert.equal(matchState(KO, "live", at(2.8)), "live");
  assert.equal(matchState(KO, "live", at(6)), "awaiting");
});
test("finished without score → awaiting", () => assert.equal(matchState(KO, "finished", at(1)), "awaiting"));
test("postponed is never playing", () => {
  assert.equal(matchState(KO, "postponed", at(1)), "postponed");
  assert.equal(matchState(KO, "postponed", at(-2)), "postponed");
});
