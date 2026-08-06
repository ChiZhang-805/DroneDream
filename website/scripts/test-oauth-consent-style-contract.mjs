import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const frontendRequire = createRequire(new URL("../../frontend/package.json", import.meta.url));
const postcss = frontendRequire("postcss");
const stylesheetUrl = new URL("../../frontend/src/site/site.css", import.meta.url);
const stylesheet = await readFile(stylesheetUrl, "utf8");
const root = postcss.parse(stylesheet, { from: stylesheetUrl.pathname });

let sharedPageRule = null;
let headingRule = null;
root.walkRules((rule) => {
  const selectors = rule.selectors ?? [];
  if (
    selectors.includes('.dd-site[data-page="account"]')
    && selectors.includes('.dd-site[data-page="oauth-consent"]')
  ) {
    sharedPageRule = rule;
  }
  if (selectors.includes(".site-auth-page-intro h1")) headingRule = rule;
});

assert(sharedPageRule, "Account and OAuth consent must share the light page surface");
assert(headingRule, "OAuth consent heading rule is missing");

const declarationValue = (rule, property) => {
  let value = null;
  rule.walkDecls(property, (declaration) => {
    value = declaration.value;
  });
  return value;
};
const background = declarationValue(sharedPageRule, "background");
const foreground = declarationValue(headingRule, "color");
assert(background, "Shared account/consent background is missing");
assert(foreground, "OAuth consent heading color is missing");

const solidBackground = [...background.matchAll(/#[0-9a-f]{6}\b/giu)].at(-1)?.[0] ?? null;
assert(solidBackground, "Shared page background must end with an opaque hex fallback");

const rgb = (hex) => {
  assert.match(hex, /^#[0-9a-f]{6}$/iu);
  return [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
};
const luminance = (hex) => rgb(hex)
  .map((channel) => (
    channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4
  ))
  .reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
const foregroundLuminance = luminance(foreground);
const backgroundLuminance = luminance(solidBackground);
const contrast = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
  / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);

assert(contrast >= 7, `OAuth consent heading contrast ${contrast.toFixed(2)} is below 7:1`);
console.log(`oauth consent style contract: ${contrast.toFixed(2)}:1 contrast`);
