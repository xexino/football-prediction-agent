// What to say about a match that has no final score yet, as of NOW (the static snapshot may be hours old).
// Pure and dependency-free so it can be unit-tested with `node --experimental-strip-types --test`.
export type MatchState = "upcoming" | "live" | "awaiting" | "postponed";

const H = 3.6e6;

export function matchState(kickoffUtc: string, phase?: string, now: number = Date.now()): MatchState {
  if (phase === "postponed") return "postponed";
  const age = now - new Date(kickoffUtc).getTime();
  if (age < 0) return "upcoming";
  if (phase === "finished") return "awaiting";
  // within 2.5 h of kickoff a match is (probably) being played, whatever the snapshot says: the backend marks any
  // started match without a live feed "awaiting_result" (council cycle 2026-11-25 18:51: Serie B showed "Finished" at 52')
  if (age < 2.5 * H) return "live";
  // a stale "live" phase never keeps a match "playing" for hours
  if (phase === "live" && age < 3 * H) return "live";
  return "awaiting";
}
