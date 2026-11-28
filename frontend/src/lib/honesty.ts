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

/** Keep a started match without a score on "today" lists for 12 h, so it does not vanish at midnight Rome while it
 *  is still being played or awaiting its result (council cycle 2026-11-26 18:50: an open-bet match disappeared). */
export function keepOnToday(isToday: boolean, kickoffUtc: string, score: string | null | undefined,
                            status?: string | null, now: number = Date.now()): boolean {
  if (isToday) return true;
  if (status === "postponed" || status === "cancelled" || status === "abandoned") return false;
  const age = now - new Date(kickoffUtc).getTime();
  return !score && age > 0 && age < 12 * 3.6e6;
}

/** "results (18 overdue), live" — the components that make overall health not HEALTHY. */
export function healthCauses(components: Record<string, any> | null | undefined): string {
  return Object.entries(components || {})
    .filter(([, c]) => c && c.state && c.state !== "HEALTHY" && c.state !== "UNKNOWN")
    .map(([k, c]) => (k === "results" && c.overdue ? `results (${c.overdue} overdue)` : k))
    .join(", ");
}
