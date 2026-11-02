import type { ReactNode } from "react";

interface SectionCardProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

export function SectionCard({
  title,
  description,
  actions,
  children,
}: SectionCardProps) {
  return (
    <section className="section-card">
      <header className="section-card-header">
        <div>
          <h2 className="section-card-title">{title}</h2>
          {description ? (
            <p className="section-card-description">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="section-card-actions">{actions}</div> : null}
      </header>
      <div className="section-card-body">{children}</div>
    </section>
  );
}
