import {
  Activity,
  BadgeCheck,
  BrainCircuit,
  Boxes,
  ChevronRight,
  Cpu,
  Database,
  GitCompareArrows,
  MonitorCog,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { useI18n } from "../../i18n/I18nProvider";
import simLockup from "../../../../brand/commercial/sim-lockup.png";
import simMark from "../../../../brand/commercial/sim-mark.png";
import { SIM_EDITION, simCopy } from "./profile";
import "./sim.css";

export function SimBrandLockup({ className = "" }: { className?: string }) {
  const classes = ["sim-brand-lockup", className].filter(Boolean).join(" ");
  return (
    <img
      className={classes}
      src={simLockup}
      alt=""
      aria-hidden="true"
      data-brand-edition="sim"
    />
  );
}

export function SimEditionBadge({ compact = false }: { compact?: boolean }) {
  const { locale } = useI18n();
  const copy = simCopy(locale);
  return (
    <span
      className={`sim-edition-badge${compact ? " sim-edition-badge-compact" : ""}`}
      data-brand-edition="sim"
    >
      <img className="sim-brand-mark" src={simMark} alt="" aria-hidden="true" />
      {copy.editionBadge}
    </span>
  );
}

export function SimEditionSettingsPanel() {
  const { locale } = useI18n();
  const copy = simCopy(locale);
  return (
    <section
      className="sim-settings-panel"
      aria-labelledby="sim-settings-title"
      data-brand-edition="sim"
    >
      <div>
        <span className="sim-settings-kicker">{copy.fixedMode}</span>
        <h3 id="sim-settings-title">{copy.settingsTitle}</h3>
        <p>{copy.settingsBody}</p>
      </div>
      <SimEditionBadge compact />
    </section>
  );
}

const SIMULATION_ITEMS = [
  { key: "simulation", icon: MonitorCog },
  { key: "px4", icon: Cpu },
  { key: "gazebo", icon: Boxes },
  { key: "vehiclePacks", icon: Database },
] as const;

const DEPENDENCY_ITEMS = [
  { key: "runtime", icon: Cpu },
  { key: "engine", icon: Boxes },
] as const;

const AUTONOMOUS_LOOP_ITEMS = [
  { key: "objective", icon: ShieldCheck },
  { key: "model", icon: BrainCircuit },
  { key: "harness", icon: Wrench },
  { key: "telemetry", icon: Activity },
  { key: "compare", icon: GitCompareArrows },
  { key: "qualify", icon: BadgeCheck },
] as const;

export function SimOverview() {
  const { locale } = useI18n();
  const copy = simCopy(locale);
  const location = useLocation();
  const blocked = new URLSearchParams(location.search).has("blocked");

  return (
    <div className="sim-overview-page" data-brand-edition="sim">
      {blocked ? (
        <section className="sim-route-blocked" role="alert" aria-labelledby="sim-blocked-title">
          <ShieldCheck aria-hidden="true" />
          <div>
            <h2 id="sim-blocked-title">{copy.blockedTitle}</h2>
            <p>{copy.blockedBody}</p>
          </div>
        </section>
      ) : null}

      <header className="sim-overview-header">
        <div>
          <span className="sim-overview-eyebrow">{copy.overviewEyebrow}</span>
          <SimBrandLockup className="sim-overview-lockup" />
          <h1 className="sr-only">{copy.overviewTitle}</h1>
          <p>{copy.overviewBody}</p>
        </div>
        <div className="sim-overview-state" aria-label={copy.previewStatus}>
          <SimEditionBadge />
          <span>{copy.previewStatus}</span>
          <code>v{SIM_EDITION.displayVersion}</code>
        </div>
      </header>

      <section className="sim-overview-band sim-loop-band" aria-labelledby="sim-loop-title">
        <div className="sim-band-heading">
          <span className="sim-settings-kicker">{copy.loopKicker}</span>
          <h2 id="sim-loop-title">{copy.loopTitle}</h2>
          <p>{copy.loopBody}</p>
          <Link className="btn btn-primary sim-loop-action" to="/jobs/new">
            {copy.startOptimization}
            <ChevronRight aria-hidden="true" />
          </Link>
        </div>
        <ol className="sim-loop-grid" aria-label={copy.loopTitle}>
          {AUTONOMOUS_LOOP_ITEMS.map(({ key, icon: Icon }, index) => (
            <li key={key}>
              <span className="sim-loop-index">{String(index + 1).padStart(2, "0")}</span>
              <Icon aria-hidden="true" />
              <div>
                <strong>{copy.loop[key].title}</strong>
                <p>{copy.loop[key].body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="sim-overview-band" aria-labelledby="sim-capability-title">
        <div className="sim-band-heading">
          <h2 id="sim-capability-title">{copy.capabilityTitle}</h2>
        </div>
        <ul className="sim-capability-grid" aria-label={copy.capabilityTitle}>
          {SIMULATION_ITEMS.map(({ key, icon: Icon }) => (
            <li className="sim-capability-item" key={key}>
              <Icon aria-hidden="true" />
              <strong>{copy.items[key]}</strong>
            </li>
          ))}
        </ul>
      </section>

      <section className="sim-overview-band sim-dependency-band" aria-labelledby="sim-dependency-title">
        <div className="sim-band-heading">
          <h2 id="sim-dependency-title">{copy.dependencyTitle}</h2>
          <p>{copy.setupBody}</p>
        </div>
        <ul className="sim-dependency-list" aria-label={copy.dependencyTitle}>
          {DEPENDENCY_ITEMS.map(({ key, icon: Icon }) => (
            <li key={key}>
              <Icon aria-hidden="true" />
              <strong>{copy.items[key]}</strong>
              <span>{copy.external}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="sim-overview-band sim-boundary-band" aria-labelledby="sim-boundary-title">
        <ShieldCheck aria-hidden="true" />
        <div>
          <h2 id="sim-boundary-title">{copy.boundaryTitle}</h2>
          <p>{copy.boundaryBody}</p>
          <strong className="sim-candidate-warning">{copy.candidateWarning}</strong>
        </div>
      </section>

      <section className="sim-setup-preview" aria-labelledby="sim-setup-preview-title">
        <div>
          <span>{copy.setupPreview}</span>
          <h2 id="sim-setup-preview-title">{SIM_EDITION.artifactFileName}</h2>
          <p>{copy.setupBody}</p>
        </div>
        <Link className="btn btn-primary" to="/desktop/setup">
          {copy.openSetup}
          <ChevronRight aria-hidden="true" />
        </Link>
      </section>
    </div>
  );
}
