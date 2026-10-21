import { Download, TerminalSquare } from "lucide-react";

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
  cliHref?: string;
}

export function ClassicHome({ release, cliHref = "/cli/" }: ClassicHomeProps) {
  return (
    <section className="site-hero site-classic-home" aria-labelledby="classic-home-title">
      <div className="site-hero-scene" aria-hidden="true">
        <DroneLaunchScene
          active
          starflightEnabled={false}
          themeOverride={WEBSITE_DRONE_THEME}
          visualOffsetX={1.58}
        />
      </div>
      <div className="site-hero-shade" aria-hidden="true" />
      <div className="site-shell site-hero-layout">
        <div className="site-hero-copy">
          <p className="site-eyebrow">NATURAL-LANGUAGE UAV ENGINEERING</p>
          <h1 id="classic-home-title">
            <span className="site-hero-line">Give Every Mission</span>
            <span className="site-hero-line site-hero-line-accent">Its Own Flight Agent.</span>
          </h1>
          <div className="site-hero-actions">
            <a className="site-button site-button-primary" href={release.downloadUrl} download={release.fileName}>
              <Download aria-hidden="true" />
              Download Universal
            </a>
            <a className="site-button site-button-ghost" href={cliHref}>
              <TerminalSquare aria-hidden="true" />
              CLI Manual
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
