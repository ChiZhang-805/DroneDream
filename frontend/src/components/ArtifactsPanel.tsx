import { Empty, ErrorState, Loading } from "./States";
import { SectionCard } from "./SectionCard";
import { ArtifactCard } from "./ArtifactCard";
import { useI18n } from "../i18n/I18nProvider";
import type { Artifact } from "../types/api";

interface ArtifactSection {
  heading: string;
  artifacts: Artifact[];
  emptyNote: string;
}

interface ArtifactsPanelProps {
  title?: string;
  description?: string;
  sections: ArtifactSection[];
  isLoading: boolean;
  error?: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
}

function ArtifactSectionGrid({ heading, artifacts, emptyNote }: ArtifactSection) {
  return (
    <div className="stack-sm">
      <h3 className="section-subheading">{heading}</h3>
      {artifacts.length === 0 ? (
        <p className="form-hint">{emptyNote}</p>
      ) : (
        <div className="artifact-grid" data-testid="artifact-grid">
          {artifacts.map((artifact) => (
            <ArtifactCard key={artifact.id} artifact={artifact} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ArtifactsPanel({
  title,
  description,
  sections,
  isLoading,
  error,
  emptyTitle,
  emptyDescription,
}: ArtifactsPanelProps) {
  const { t } = useI18n();
  const total = sections.reduce((acc, s) => acc + s.artifacts.length, 0);

  return (
    <SectionCard title={title ?? t("artifacts.title")} description={description}>
      {isLoading ? (
        <Loading label={t("artifacts.loading")} />
      ) : error ? (
        <ErrorState
          title={t("artifacts.loadFailed")}
          description={error}
        />
      ) : total === 0 ? (
        <Empty
          title={emptyTitle ?? t("artifacts.emptyTitle")}
          description={emptyDescription ?? t("artifacts.emptyDescription")}
        />
      ) : (
        <div className="stack-md">
          {sections.map((section) => (
            <ArtifactSectionGrid key={section.heading} {...section} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}
