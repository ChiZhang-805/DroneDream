import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("manual sidebar stylesheet contract", () => {
  const stylesheet = readFileSync(
    resolve(process.cwd(), "src/site/aliyun-manual-community.css"),
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
});
