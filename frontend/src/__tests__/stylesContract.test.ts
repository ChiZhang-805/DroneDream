import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import postcss from "postcss";
import { describe, expect, it } from "vitest";

describe("console stylesheet contract", () => {
  it("parses and defines every referenced custom property", () => {
    const source = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    const root = postcss.parse(source, { from: "styles.css" });
    const defined = new Set<string>();
    const referenced = new Set<string>();

    root.walkDecls((declaration) => {
      if (declaration.prop.startsWith("--")) defined.add(declaration.prop);
      for (const match of declaration.value.matchAll(/var\((--[\w-]+)/g)) {
        const name = match[1];
        if (name) referenced.add(name);
      }
    });

    expect(
      [...referenced].filter((name) => !defined.has(name)).sort(),
    ).toEqual([]);
  });
});
