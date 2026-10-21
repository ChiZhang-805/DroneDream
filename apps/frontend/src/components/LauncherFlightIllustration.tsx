import campusIllustration from "../assets/launcher-campus.png";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

type LauncherFlightIllustrationProps = {
  active?: boolean;
  description: string;
  progress?: number | null;
  title: string;
};

export function LauncherFlightIllustration({ active = false, progress = null, title }: LauncherFlightIllustrationProps) {
  const reducedMotion = usePrefersReducedMotion();
  return (
    <section className="launcher-flight-illustration" data-active={active} data-reduced-motion={reducedMotion}
      data-progress={Math.max(0, Math.min(100, progress ?? 0))} aria-label={title}>
      <div className="launcher-flight-art" aria-hidden="true">
        <img className="launcher-flight-image" src={campusIllustration} alt="" fetchPriority="high" />
      </div>
    </section>
  );
}
