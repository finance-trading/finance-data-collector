/** Compact relative time: "just now" / "5m" / "3h" / "2d" / "Jan 5". */
export function relativeTime(iso: string | null, nowMs: number = Date.now()): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const diff = nowMs - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h`;
  if (diff < 7 * 86_400_000) return `${Math.round(diff / 86_400_000)}d`;
  return new Date(then).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
