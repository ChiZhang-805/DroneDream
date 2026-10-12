import campusIllustration from "../assets/launcher-campus.png";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

type LauncherFlightIllustrationProps = {
  active?: boolean;
  description: string;
  progress?: number | null;
  title: string;
};

export function LauncherFlightIllustration({ active = false, description, progress = null, title }: LauncherFlightIllustrationProps) {
  const reducedMotion = usePrefersReducedMotion();
  return (
    <section className="launcher-flight-illustration" data-active={active} data-reduced-motion={reducedMotion}
      data-progress={Math.max(0, Math.min(100, progress ?? 0))} aria-labelledby="launcher-flight-title">
      <div className="launcher-flight-art" aria-hidden="true">
        <img className="launcher-flight-image" src={campusIllustration} alt="" fetchPriority="high" />
      </div>
      <div className="launcher-flight-copy">
        <h1 id="launcher-flight-title">{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
    </section>
  );
}
