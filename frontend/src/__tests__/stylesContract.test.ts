import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

import postcss from "postcss";
import { describe, expect, it } from "vitest";

describe("console stylesheet contract", () => {
  it("parses and defines every referenced custom property", () => {
    const pending = [resolve(process.cwd(), "src/styles.css")];
    const visited = new Set<string>();
    const roots: postcss.Root[] = [];
    while (pending.length > 0) {
      const stylesheetPath = pending.pop();
      if (!stylesheetPath || visited.has(stylesheetPath)) continue;
      visited.add(stylesheetPath);
      const source = readFileSync(stylesheetPath, "utf8");
      const root = postcss.parse(source, { from: stylesheetPath });
      roots.push(root);
      root.walkAtRules("import", (rule) => {
        const imported = rule.params.match(/^["']([^"']+)["']/u)?.[1];
        if (imported?.startsWith(".")) {
          pending.push(resolve(dirname(stylesheetPath), imported));
        }
      });
    }
    const defined = new Set<string>();
    const referenced = new Set<string>();

    for (const root of roots) {
      root.walkDecls((declaration) => {
        if (declaration.prop.startsWith("--")) defined.add(declaration.prop);
        for (const match of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
          const name = match[1];
          if (name) referenced.add(name);
        }
      });
    }

    expect(
      [...referenced].filter((name) => !defined.has(name)).sort(),
    ).toEqual([]);
  });
});
