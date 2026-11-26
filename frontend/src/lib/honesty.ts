// Small, pure wording helpers for the owner-facing pages (council cycle 2026-11-26 00:50).

/** Bets placed before the owner switched to €500 capital / €10 flat stakes (2026-11-25 21:21 UTC) used €1. */
export const STAKE_RULE_CHANGE = "2026-11-25T21:21:00Z";

export function legacyStake(createdAt: string | null | undefined): boolean {
  if (!createdAt) return false;
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(createdAt) ? createdAt : createdAt + "Z"; // export times are UTC
  return new Date(iso).getTime() < new Date(STAKE_RULE_CHANGE).getTime();
}

/** A delayed live score older than this is no longer "the score now". */
export const LIVE_FRESH_MIN = 20;

export function liveScoreText(score: string, ageMin: number): string {
  return ageMin <= LIVE_FRESH_MIN
    ? `${score} (delayed score, ${ageMin} min old)`
    : `last score seen ${score}, ${ageMin} min ago (no newer update yet)`;
}

/** Below this many settled bets, ROI and win rate are not shown as headline percentages. */
export const MIN_SAMPLE = 20;
export const smallSample = (settled: number | null | undefined) => (settled ?? 0) < MIN_SAMPLE;
export const sampleNote = (settled: number | null | undefined) =>
  `${settled ?? 0} settled bet${settled === 1 ? "" : "s"}: not meaningful yet (needs ${MIN_SAMPLE}+)`;
