import type { ProfileCheck } from './types'

// Scorer warnings describe interpretation; only workload mismatches block a winner.
export function comparisonState(
  mismatches: string[],
  profiles: string[],
  checks: Record<string, ProfileCheck> = {},
) {
  const warnings = new Map<string, ProfileCheck>()
  for (const profile of profiles) {
    const check = checks[profile]
    if (check && check.severity !== 'ok') warnings.set(profile, check)
  }
  return { comparable: mismatches.length === 0, warnings }
}
