import type { ReactNode } from "react";

type AlertTone = "info" | "success" | "warning" | "danger";

interface AlertProps {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
}

/** Urgent failures use an alert; routine updates use status without initiating any side effect. */
export function Alert({ tone = "info", title, children }: AlertProps) {
  return (
    <div className={`alert alert-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      {title ? <div className="alert-title">{title}</div> : null}
      {children ? <div className="alert-body">{children}</div> : null}
    </div>
  );
}
