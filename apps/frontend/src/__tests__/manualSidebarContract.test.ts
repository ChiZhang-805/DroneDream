import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("manual sidebar stylesheet contract", () => {
  const stylesheet = readFileSync(
    resolve(process.cwd(), "src/site/aliyun-manual-community.css"),
    "utf8",
  );
  const manualPage = readFileSync(
    resolve(process.cwd(), "src/site/ManualPage.tsx"),
    "utf8",
  );
  const architecturePage = readFileSync(
    resolve(process.cwd(), "src/site/ManualArchitecture.tsx"),
    "utf8",
  );
  const architectureData = readFileSync(
    resolve(process.cwd(), "src/site/manualArchitectureData.ts"),
    "utf8",
  );

  it("hides the sidebar scrollbar while keeping the contents scrollable", () => {
    expect(stylesheet).toMatch(/\.manual-sidebar\s*\{[\s\S]*?scrollbar-width:\s*none;/u);
    expect(stylesheet).toMatch(
      /\.manual-sidebar::-webkit-scrollbar\s*\{[\s\S]*?display:\s*none;/u,
    );
  });

  it("keeps the collapsed control transparent until hover or keyboard focus", () => {
    expect(stylesheet).toMatch(/\.manual-sidebar-toggle\s*\{[\s\S]*?background:\s*transparent;/u);
    expect(stylesheet).toMatch(
      /\.manual-sidebar-toggle:hover,[\s\S]*?\.manual-sidebar-toggle:focus-visible\s*\{[\s\S]*?background:\s*rgba\(255,\s*255,\s*255,\s*0\.92\);/u,
    );
  });

  it("offers an accessible two-way switch between the manual and architecture views", () => {
    expect(manualPage).toContain('aria-label={manualView === "manual" ? copy.openArchitecture : copy.openManual}');
    expect(manualPage).toContain('<ManualArchitecture locale={locale} section={architectureSection} />');
    expect(stylesheet).toMatch(
      /\.manual-mode-switch\s*\{[\s\S]*?position:\s*fixed;[\s\S]*?right:[^;]+;[\s\S]*?bottom:[^;]+;/u,
    );
    expect(manualPage.indexOf('className="manual-mode-switch"')).toBeGreaterThan(
      manualPage.indexOf("</aside>"),
    );
  });

  it("uses one reader width and typography scale across manual and architecture content", () => {
    expect(stylesheet).toContain("--manual-reader-max-width: 1080px;");
    expect(stylesheet).toContain("--manual-prose-max-width: 76ch;");
    expect(stylesheet).toMatch(
      /\.site-manual-page\.is-architecture-view \.manual-reader-header,[\s\S]*?var\(--manual-reader-max-width\)/u,
    );
    expect(stylesheet).toMatch(
      /\.manual-architecture-page\s*\{[\s\S]*?font-size:\s*var\(--manual-copy-size\);/u,
    );
    expect(stylesheet).toMatch(
      /\.manual-architecture-intro h2\s*\{[\s\S]*?font-size:\s*var\(--manual-chapter-title-size\);/u,
    );
    expect(stylesheet).toMatch(
      /\.architecture-map-pair\s*\{[\s\S]*?width:\s*min\(100%,\s*var\(--manual-prose-max-width\)\);/u,
    );
  });

  it("ships both same-footprint map views used by the architecture comparison", () => {
    const assets = [
      "architecture-map-human.webp",
      "architecture-map-processing.webp",
      "architecture-map-structured.webp",
    ];
    for (const asset of assets) {
      const assetPath = resolve(process.cwd(), "public/docs/downloads/manual-assets", asset);
      expect(existsSync(assetPath)).toBe(true);
      expect(statSync(assetPath).size).toBeGreaterThan(100_000);
      expect(architecturePage).toContain(`/docs/downloads/manual-assets/${asset}`);
    }
  });

  it("keeps the map explanation narrative and removes the formula card", () => {
    expect(architecturePage).toContain("firstTransitionBody");
    expect(architecturePage).toContain("secondTransitionBody");
    expect(architecturePage).not.toContain("architecture-formula");
    expect(architecturePage).not.toContain("Map = geometry + semantics + topology");
    expect(stylesheet).toMatch(
      /\.architecture-map-transition > header > span\s*\{[\s\S]*?font-size:\s*var\(--manual-section-title-size\);/u,
    );
  });

  it("presents the backend map contracts as a copyable JSON example", () => {
    expect(architecturePage).toContain("MapFeaturePoint and MapRouteEdge contracts");
    expect(architecturePage).toContain('"point_id": "chemicum"');
    expect(architecturePage).toContain('"direction": "bidirectional"');
    expect(architecturePage).toContain("navigator.clipboard?.writeText");
    expect(architecturePage).toContain('copied ? <Check aria-hidden="true" />');
    expect(stylesheet).toMatch(
      /\.architecture-json-example:hover > button,[\s\S]*?opacity:\s*1;/u,
    );
  });

  it("expands every code example to its complete height without a vertical scroller", () => {
    expect(stylesheet).toMatch(
      /\.architecture-json-example pre\s*\{[\s\S]*?max-height:\s*none;[\s\S]*?overflow-y:\s*hidden;/u,
    );
    expect(architecturePage).toContain('language="python"');
    expect(architecturePage).toContain("token-keyword");
  });

  it("uses the manual chapter hierarchy for both architecture chapters", () => {
    expect(architectureData).toContain('label: "Map is not a map"');
    expect(architectureData).toContain('label: "Drone is not a drone"');
    expect(architectureData).toContain('id: "architecture-map-transition-three"');
    expect(architectureData).toContain('id: "architecture-drone-transition-three"');
    expect(manualPage).toContain('className="manual-nav-chapter-row"');
    expect(manualPage).toContain('className="manual-nav-subsections"');
    expect(manualPage).toContain("toggleArchitectureChapter");
  });

  it("documents the real aircraft contract and its map-specific 3D corridor", () => {
    expect(architecturePage).toContain("Drone is not a drone");
    expect(architecturePage).toContain('"asset_id": "aircraft-my-drone"');
    expect(architecturePage).toContain('"body_radius_m": 0.38');
    expect(architecturePage).toContain('"simulation_targets": ["PX4 v1.16", "MAVSDK"]');
    expect(architecturePage).toContain('id="architecture-drone-transition-one"');
    expect(architecturePage).toContain('id="architecture-drone-transition-two"');
    expect(architecturePage).toContain('id="architecture-drone-transition-three"');
    expect(stylesheet).toMatch(/\.architecture-drone-product\s*\{[\s\S]*?grid-template-columns:/u);
    expect(stylesheet).toMatch(/\.architecture-airspace-diagram\s*\{[\s\S]*?var\(--manual-prose-max-width\)/u);
  });

  it("uses rendered aircraft and volumetric corridor assets instead of inline drone drawings", () => {
    const assets = ["architecture-drone-x500.webp", "architecture-airspace-corridor.webp"];
    for (const asset of assets) {
      const assetPath = resolve(process.cwd(), "public/docs/downloads/manual-assets", asset);
      expect(existsSync(assetPath)).toBe(true);
      expect(statSync(assetPath).size).toBeGreaterThan(250_000);
      expect(architecturePage).toContain(`/docs/downloads/manual-assets/${asset}`);
    }
    expect(architecturePage).not.toContain("function DroneIllustration");
    expect(architecturePage).not.toContain('<linearGradient id="airspace-corridor"');
    expect(architecturePage).toContain('className="architecture-drone-baseline"');
    expect(architecturePage.match(/className="architecture-drone-target"/gu)).toHaveLength(1);
  });

  it("opens the architecture contents and ships the five-part model workflow", () => {
    expect(manualPage).toContain('() => new Set(["map", "drone", "model"])');
    expect(manualPage).toContain("setSidebarOpen(true);");
    expect(architectureData).toContain('label: "The model is not the system"');
    expect(architectureData).toContain('id: "architecture-model-transition-five"');
    expect(architecturePage).toContain("route.plan_global_corridor");
    expect(architecturePage).toContain("mission.validate_plan");
    expect(architecturePage).toContain("dronedream.autonomy.planner-response.v1");
    expect(architecturePage).toContain("ModelVisionEvidence");
    expect(architecturePage).toContain("HarnessFlow");
  });
});
