import { Download, Sparkles } from "lucide-react";
import { useRef } from "react";

import { DroneLaunchScene } from "../components/DroneLaunchScene";
import type { WebsiteRelease } from "./release";

const WEBSITE_DRONE_THEME = Object.freeze({
  primary: 0x68e8ff,
  secondary: 0x9b72ff,
  tertiary: 0xf166d8,
  darkSurface: 0x070913,
  fog: 0x070913,
  gridMinor: 0x34244f,
});

interface ClassicHomeProps {
  release: WebsiteRelease;
}

export function ClassicHome({ release }: ClassicHomeProps) {
  const droneFlightRef = useRef<(() => void) | null>(null);

  return (
    <section className="site-hero site-classic-home" aria-labelledby="classic-home-title">
      <div className="site-hero-scene" aria-hidden="true">
        <DroneLaunchScene
          active
          starflightControllerRef={droneFlightRef}
          themeOverride={WEBSITE_DRONE_THEME}
          visualOffsetX={1.58}
        />
      </div>
      <div className="site-hero-shade" aria-hidden="true" />
      <div className="site-shell site-hero-layout">
        <div className="site-hero-copy">
          <p className="site-eyebrow">NATURAL-LANGUAGE UAV ENGINEERING</p>
          <h1 id="classic-home-title">
            <span className="site-hero-line">Describe the mission.</span>
            <span className="site-hero-line site-hero-line-accent">See it take flight.</span>
          </h1>
          <div className="site-hero-actions">
            <a className="site-button site-button-primary" href={release.downloadUrl} download={release.fileName}>
              <Download aria-hidden="true" />
              Download Universal
            </a>
            <button className="site-button site-button-ghost" type="button" onClick={() => droneFlightRef.current?.()}>
              <Sparkles aria-hidden="true" />
              Launch starflight
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
