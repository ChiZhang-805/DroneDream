import type { ReactNode } from "react";

type AlertTone = "info" | "success" | "warning" | "danger";

interface AlertProps {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
}

export function Alert({ tone = "info", title, children }: AlertProps) {
  return (
    <div className={`alert alert-${tone}`} role="status">
      {title ? <div className="alert-title">{title}</div> : null}
      {children ? <div className="alert-body">{children}</div> : null}
    </div>
  );
}
