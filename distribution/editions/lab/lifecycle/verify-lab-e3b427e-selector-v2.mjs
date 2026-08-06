import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const inspectorPath = resolve(scriptDirectory, "inspect-lab-e3b427e-live-webview2.mjs");
const require = createRequire(import.meta.url);
const { JSDOM } = require("../../../../frontend/node_modules/jsdom");

const inspectorSource = readFileSync(inspectorPath, "utf8");
const selectorMatch = inspectorSource.match(
  /const LAB_APP_SHELL_SELECTOR = '([^']+)';/u,
);
if (!selectorMatch) {
  throw new Error("The Lab inspector selector contract is missing.");
}
const selector = selectorMatch[1];

const fixtures = [
  {
    id: "lab-root-and-shell",
    html: '<html data-brand-edition="lab"><body><div class="app-shell"></div></body></html>',
    expected: true,
  },
  {
    id: "wrong-sim-edition",
    html: '<html data-brand-edition="sim"><body><div class="app-shell"></div></body></html>',
    expected: false,
  },
  {
    id: "missing-edition-attribute",
    html: '<html><body><div class="app-shell"></div></body></html>',
    expected: false,
  },
  {
    id: "missing-app-shell",
    html: '<html data-brand-edition="lab"><body><main></main></body></html>',
    expected: false,
  },
];

const results = fixtures.map((fixture) => {
  const dom = new JSDOM(fixture.html);
  const accepted = dom.window.document.querySelector(selector) !== null;
  if (accepted !== fixture.expected) {
    throw new Error(`Selector fixture ${fixture.id} returned ${accepted}.`);
  }
  return { id: fixture.id, expected: fixture.expected, accepted };
});

console.log(JSON.stringify({ selector, fixtureCount: results.length, results }));
