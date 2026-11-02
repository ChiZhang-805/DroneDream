import campusIllustration from "../assets/launcher-campus.png";
import universalIllustration from "../assets/launcher-campus-universal.png";
import simIllustration from "../assets/launcher-campus-sim.png";
import labIllustration from "../assets/launcher-campus-lab.png";
import fieldIllustration from "../assets/launcher-campus-field.png";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useEditionTheme } from "../theme/EditionThemeProvider";

const CAMPUS_ILLUSTRATIONS = {
  universal: universalIllustration,
  sim: simIllustration,
  lab: labIllustration,
  field: fieldIllustration,
  autonomy: campusIllustration,
} as const;

type LauncherFlightIllustrationProps = {
  active?: boolean;
  description: string;
  progress?: number | null;
  title: string;
};

export function LauncherFlightIllustration({ active = false, progress = null, title }: LauncherFlightIllustrationProps) {
  const reducedMotion = usePrefersReducedMotion();
  const { id: edition } = useEditionTheme();
  return (
    <section className="launcher-flight-illustration" data-active={active} data-reduced-motion={reducedMotion}
      data-progress={Math.max(0, Math.min(100, progress ?? 0))} aria-label={title}>
      <div className="launcher-flight-art" aria-hidden="true">
        <img className="launcher-flight-image" src={CAMPUS_ILLUSTRATIONS[edition]} alt="" fetchPriority="high" />
      </div>
    </section>
  );
}
