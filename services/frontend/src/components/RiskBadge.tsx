import type { RiskLevel } from "../types";

const styles: Record<RiskLevel, string> = {
  high: "bg-rose-500/15 text-high border-rose-400/30",
  medium: "bg-amber-400/15 text-medium border-amber-300/30",
  low: "bg-emerald-400/15 text-low border-emerald-300/30",
};

export function RiskBadge({ level }: { level?: RiskLevel | null }) {
  if (!level) {
    return (
      <span className="inline-flex items-center rounded-full border border-line px-2 py-0.5 text-xs text-mute">
        not scored
      </span>
    );
  }
  const mark = level === "high" ? "●" : level === "medium" ? "●" : "●";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs capitalize ${styles[level]}`}>
      <span aria-hidden>{mark}</span>
      {level}
    </span>
  );
}

export function riskBarColor(level?: RiskLevel | null) {
  if (level === "high") return "#fb7185";
  if (level === "medium") return "#fbbf24";
  if (level === "low") return "#34d399";
  return "#8b9bb8";
}
