import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state-block state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

interface EmptyProps {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function Empty({ title = "Nothing here yet", description, action }: EmptyProps) {
  return (
    <div className="state-block state-empty">
      <div className="state-title">{title}</div>
      {description ? <div className="state-description">{description}</div> : null}
      {action ? <div className="state-action">{action}</div> : null}
    </div>
  );
}

interface ErrorStateProps {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function ErrorState({
  title = "Something went wrong",
  description,
  action,
}: ErrorStateProps) {
  return (
    <div className="state-block state-error" role="alert">
      <div className="state-title">{title}</div>
      {description ? <div className="state-description">{description}</div> : null}
      {action ? <div className="state-action">{action}</div> : null}
    </div>
  );
}
