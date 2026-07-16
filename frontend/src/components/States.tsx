import type { ReactNode } from "react";
import { useI18n } from "../i18n/I18nProvider";

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="state-block state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      <span>{label ?? t("states.loading")}</span>
    </div>
  );
}

interface EmptyProps {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function Empty({ title, description, action }: EmptyProps) {
  const { t } = useI18n();
  return (
    <div className="state-block state-empty">
      <div className="state-title">{title ?? t("states.emptyTitle")}</div>
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
  title,
  description,
  action,
}: ErrorStateProps) {
  const { t } = useI18n();
  return (
    <div className="state-block state-error" role="alert">
      <div className="state-title">{title ?? t("states.errorTitle")}</div>
      {description ? <div className="state-description">{description}</div> : null}
      {action ? <div className="state-action">{action}</div> : null}
    </div>
  );
}
