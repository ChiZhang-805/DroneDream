import { readFileSync, readdirSync } from "node:fs";
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

  it("keeps the autonomy conversation and composer on one responsive width contract", () => {
    const source = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    const root = postcss.parse(source);
    const declarations = new Map<string, Map<string, string>>();

    root.walkRules((rule) => {
      const selectorDeclarations = declarations.get(rule.selector) ?? new Map<string, string>();
      rule.walkDecls((declaration) => {
        selectorDeclarations.set(declaration.prop, declaration.value);
      });
      declarations.set(rule.selector, selectorDeclarations);
    });

    expect(declarations.get(".autonomy-command-page")?.get("--autonomy-chat-column-width")).toBe("76rem");
    expect(declarations.get(".autonomy-command-page")?.get("grid-template-columns")).toBe(
      "minmax(0, min(100%, var(--autonomy-chat-column-width)))",
    );
    expect(declarations.get(".autonomy-command-stage")?.get("width")).toBe(
      "100%",
    );
    expect(declarations.get(".autonomy-command-stage")?.get("justify-self")).toBe("stretch");
    expect(declarations.get(".autonomy-conversation-thread")?.get("width")).toBe(
      "min(100%, var(--autonomy-chat-column-width))",
    );
    expect(declarations.get(".autonomy-command-page .autonomy-command-composer")?.get("width")).toBe(
      "min(100%, var(--autonomy-chat-column-width))",
    );
  });

  it("keeps every desktop application surface on the canonical light theme", () => {
    const applicationStylesheets = readdirSync(resolve(process.cwd(), "src"), {
      recursive: true,
      withFileTypes: true,
    })
      .filter((entry) => entry.isFile() && entry.name.endsWith(".css"))
      .map((entry) => resolve(entry.parentPath, entry.name))
      .filter((stylesheetPath) => !stylesheetPath.includes(`${process.platform === "win32" ? "\\" : "/"}site${process.platform === "win32" ? "\\" : "/"}`));
    const forbiddenDarkTokens = [
      "--dd-brand-dark-surface",
      "#000000",
      "#050611",
      "#070913",
      "#08091a",
      "#090212",
      "#09071b",
      "#0d0e13",
      "#101326",
      "#11121d",
      "#111522",
      "#11162c",
      "#171119",
      "#211031",
      "#282b3c",
      "#292a31",
      "#2a2e41",
      "#3a3b43",
    ];
    const surfaceSelector = /(?:^|[\s>+~.,:#])(?:html|body|button|input|select|textarea|dialog|[^\s,{]*(?:shell|sidebar|header|footer|panel|card|menu|popover|modal|backdrop|launcher|settings|composer|controls|screen|viewer|workspace|repository|command)[^\s,{]*)/iu;
    const visualContentSelector = /(?:canvas|scene|model|drone|mesh|preview-image|camera-feed|status-dot|logo|icon)/iu;
    const violations: string[] = [];

    for (const stylesheetPath of applicationStylesheets) {
      const relativePath = stylesheetPath.slice(process.cwd().length + 1);
      const root = postcss.parse(readFileSync(stylesheetPath, "utf8"), { from: stylesheetPath });
      root.walkDecls((declaration) => {
        if (declaration.prop === "color-scheme" && declaration.value.trim().toLowerCase() === "dark") {
          violations.push(`${relativePath}:${declaration.source?.start?.line ?? 0} color-scheme: dark`);
          return;
        }
        if (!/^background(?:-color)?$/u.test(declaration.prop)) return;
        const selector = declaration.parent?.type === "rule" ? declaration.parent.selector : "";
        if (!surfaceSelector.test(selector) || visualContentSelector.test(selector)) return;
        const normalized = declaration.value.toLowerCase();
        const forbidden = forbiddenDarkTokens.find((token) => normalized.includes(token));
        if (forbidden) {
          violations.push(
            `${relativePath}:${declaration.source?.start?.line ?? 0} ${selector} uses ${forbidden}`,
          );
        }
      });
    }

    expect(violations).toEqual([]);
  });

  it("keeps native scrollbar rails hidden across the shared desktop and console surface", () => {
    const stylesheet = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    const root = postcss.parse(stylesheet);
    const universalRule = root.nodes.find((node) => (
      node.type === "rule"
      && node.selector?.includes("*::before")
      && node.selector?.includes("*::after")
      && node.nodes.some((child) => (
        child.type === "decl"
        && child.prop === "scrollbar-width"
        && child.value === "none"
        && child.important
      ))
    ));
    const webkitRule = root.nodes.find((node) => (
      node.type === "rule"
      && node.selector === "*::-webkit-scrollbar"
      && node.nodes.some((child) => (
        child.type === "decl"
        && child.prop === "display"
        && child.value === "none"
        && child.important
      ))
    ));

    expect(universalRule).toBeDefined();
    expect(webkitRule).toBeDefined();
  });
});
