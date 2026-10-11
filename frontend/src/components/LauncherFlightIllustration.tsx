import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

type LauncherFlightIllustrationProps = {
  active?: boolean;
  description: string;
  progress?: number | null;
  title: string;
};

/**
 * Lightweight startup illustration used by the desktop editions.
 *
 * The launcher deliberately avoids WebGL and downloaded scene assets so the
 * environment checks remain responsive on machines whose graphics/runtime
 * stack is still being prepared. The real map and vehicle viewers continue to
 * use their qualified 3D assets after the workspace opens.
 */
export function LauncherFlightIllustration({
  active = false,
  description,
  progress = null,
  title,
}: LauncherFlightIllustrationProps) {
  const reducedMotion = usePrefersReducedMotion();
  const normalizedProgress = progress === null
    ? 0
    : Math.max(0, Math.min(100, progress));

  return (
    <section
      className="launcher-flight-illustration"
      data-active={active ? "true" : "false"}
      data-reduced-motion={reducedMotion ? "true" : "false"}
      data-progress={normalizedProgress}
      aria-labelledby="launcher-flight-title"
    >
      <div className="launcher-flight-art" aria-hidden="true">
        <span className="launcher-flight-orb launcher-flight-orb-a" />
        <span className="launcher-flight-orb launcher-flight-orb-b" />
        <svg
          className="launcher-flight-map"
          viewBox="0 0 720 500"
          role="presentation"
        >
          <defs>
            <linearGradient id="launcher-building" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ffffff" />
              <stop offset="1" stopColor="#eef1f7" />
            </linearGradient>
            <linearGradient id="launcher-route" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#ff3f68" />
              <stop offset="0.55" stopColor="#d84cc7" />
              <stop offset="1" stopColor="#43b8c5" />
            </linearGradient>
            <filter id="launcher-shadow" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="12" stdDeviation="12" floodColor="#7e7790" floodOpacity="0.16" />
            </filter>
          </defs>

          <path className="launcher-flight-road" d="M42 382 C168 322 220 357 312 289 S493 187 676 121" />
          <path className="launcher-flight-road launcher-flight-road-secondary" d="M92 102 C184 157 234 156 315 119 S493 85 635 182" />

          <g className="launcher-flight-buildings" fill="url(#launcher-building)" filter="url(#launcher-shadow)">
            <rect x="74" y="217" width="126" height="104" rx="24" />
            <rect x="229" y="166" width="104" height="88" rx="22" />
            <rect x="386" y="268" width="132" height="98" rx="24" />
            <rect x="527" y="92" width="112" height="112" rx="26" />
          </g>
          <g className="launcher-flight-windows" fill="#dfe5ef">
            <rect x="101" y="243" width="22" height="20" rx="5" />
            <rect x="139" y="243" width="34" height="20" rx="5" />
            <rect x="257" y="191" width="48" height="19" rx="5" />
            <rect x="414" y="295" width="30" height="20" rx="5" />
            <rect x="458" y="295" width="32" height="20" rx="5" />
            <rect x="556" y="120" width="54" height="20" rx="5" />
            <rect x="556" y="153" width="34" height="20" rx="5" />
          </g>

          <path
            className="launcher-flight-route-base"
            d="M115 361 C172 307 247 329 291 273 C338 214 387 241 430 199 C481 149 531 191 592 132"
          />
          <path
            className="launcher-flight-route-progress"
            d="M115 361 C172 307 247 329 291 273 C338 214 387 241 430 199 C481 149 531 191 592 132"
            pathLength="100"
            style={{ strokeDashoffset: 100 - normalizedProgress }}
          />

          <g className="launcher-flight-pin launcher-flight-pin-start" transform="translate(115 361)">
            <circle r="17" />
            <circle r="6" />
          </g>
          <g className="launcher-flight-pin launcher-flight-pin-end" transform="translate(592 132)">
            <circle r="17" />
            <circle r="6" />
          </g>

          <g className="launcher-flight-drone">
            {!reducedMotion && active ? (
              <animateMotion
                dur="7.5s"
                repeatCount="indefinite"
                rotate="auto"
                path="M115 361 C172 307 247 329 291 273 C338 214 387 241 430 199 C481 149 531 191 592 132"
              />
            ) : null}
            <g transform="translate(-28 -28)">
              <circle className="launcher-flight-drone-halo" cx="28" cy="28" r="27" />
              <path className="launcher-flight-drone-arm" d="M13 15 L43 41 M43 15 L13 41" />
              <rect className="launcher-flight-drone-body" x="20" y="20" width="16" height="16" rx="6" />
              <g className="launcher-flight-rotor">
                <ellipse cx="12" cy="14" rx="11" ry="4" />
                <ellipse cx="44" cy="14" rx="11" ry="4" />
                <ellipse cx="12" cy="42" rx="11" ry="4" />
                <ellipse cx="44" cy="42" rx="11" ry="4" />
              </g>
            </g>
          </g>
        </svg>

        <div className="launcher-flight-legend">
          <span><i className="launcher-flight-legend-drone" /> UAV</span>
          <span><i className="launcher-flight-legend-route" /> 3D route</span>
        </div>
      </div>

      <div className="launcher-flight-copy">
        <h1 id="launcher-flight-title">{title}</h1>
        <p>{description}</p>
      </div>
    </section>
  );
}
