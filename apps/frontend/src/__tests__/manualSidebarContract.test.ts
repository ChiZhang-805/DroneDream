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
});
