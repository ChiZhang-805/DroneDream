import type { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "positive" | "negative" | "muted";
}

export function MetricCard({
  label,
  value,
  sub,
  tone = "default",
}: MetricCardProps) {
  return (
    <div className={`metric-card metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub ? <div className="metric-sub">{sub}</div> : null}
    </div>
  );
}
