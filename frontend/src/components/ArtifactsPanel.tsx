import { Empty, Loading } from "./States";
import { SectionCard } from "./SectionCard";
import { ArtifactCard } from "./ArtifactCard";
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
  title = "Artifacts",
  description,
  sections,
  isLoading,
  emptyTitle = "No artifacts yet",
  emptyDescription = "Artifacts will appear after this job finishes.",
}: ArtifactsPanelProps) {
  const total = sections.reduce((acc, s) => acc + s.artifacts.length, 0);

  return (
    <SectionCard title={title} description={description}>
      {isLoading ? (
        <Loading label="Loading artifacts…" />
      ) : total === 0 ? (
        <Empty title={emptyTitle} description={emptyDescription} />
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
