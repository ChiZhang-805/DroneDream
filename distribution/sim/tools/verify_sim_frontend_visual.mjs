import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(scriptPath), "../../..");
const frontendRoot = path.join(repoRoot, "frontend");
const contractPath = path.join(
  repoRoot,
  "distribution/sim/frontend/visual-acceptance.v1.json",
);
const args = new Map(
  process.argv.slice(2).map((argument) => {
    const [key, ...value] = argument.split("=");
    return [key, value.join("=") || true];
  }),
);
const contractOnly = args.has("--contract-only");
const yellowAcknowledged = args.has("--ack-yellow");
const donorManifestArgument = args.get("--donor-manifest");

if (contractOnly === yellowAcknowledged) {
  throw new Error("Choose exactly one mode: --contract-only or --ack-yellow");
}

function git(...gitArgs) {
  return execFileSync("git", gitArgs, {
    cwd: repoRoot,
    encoding: "utf8",
  }).trim();
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function assertExactKeys(value, expected, label) {
  assert(value && typeof value === "object" && !Array.isArray(value), `${label} must be an object`);
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), `${label} keys drifted`);
}

function resolveRepoFile(relativePath) {
  assert(
    typeof relativePath === "string"
      && /^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\/[A-Za-z0-9][A-Za-z0-9_.-]*)*$/.test(relativePath),
    `Unsafe repository path: ${relativePath}`,
  );
  const resolved = path.resolve(repoRoot, relativePath);
  assert(resolved.startsWith(`${repoRoot}${path.sep}`), `Repository path escaped: ${relativePath}`);
  return resolved;
}

async function loadAndValidateContract() {
  const contract = JSON.parse(await readFile(contractPath, "utf8"));
  assertExactKeys(contract, [
    "schemaVersion",
    "kind",
    "contractVersion",
    "editionId",
    "executionClass",
    "requiredAcknowledgement",
    "networkPolicy",
    "apiKeyUseAllowed",
    "productIdentity",
    "brandDonor",
    "source",
    "viewports",
    "locales",
    "routes",
    "requiredAssertions",
    "screenshots",
    "receipt",
    "nonClaims",
  ], "contract");
  assert.equal(contract.schemaVersion, 1);
  assert.equal(contract.kind, "dronedream-sim-frontend-visual-acceptance");
  assert.equal(contract.contractVersion, "1.0.0");
  assert.equal(contract.editionId, "sim");
  assert.equal(contract.executionClass, "YELLOW-offline-browser");
  assert.equal(contract.requiredAcknowledgement, "--ack-yellow");
  assert.equal(contract.networkPolicy, "local-vite-with-offline-503-api-fixture");
  assert.equal(contract.apiKeyUseAllowed, false);
  assert.deepEqual(contract.productIdentity, {
    displayName: "DroneDream · SIM",
    artifactFileName: "DroneDream-Sim-1.0.0.exe",
    releaseState: "internal-preview",
    validationState: "planned-not-validated",
  });
  assert.deepEqual(contract.brandDonor, {
    approvedConceptHandoffSha256: "9fc52dea2edab1b65aa8c814fbf05ff1ad4fea0de4980403bec84dab8a1d9657",
    intakePath: "distribution/sim/brand/donor-intake.v1.json",
    intakeSha256: "a68d02430de5c1aebc42faed6f9e087731b6d94e6f0a7fa15c558b44e5b93297",
    approvedEditionAssetManifestPath: "distribution/sim/brand/approved-edition-assets.v1.json",
    approvedEditionAssetManifestSha256: "a9b868c7d174eea1568ef954246f05cc21cbae767bd26a99501f0eb285af0724",
    approvedEditionAssetState: "vendored-exact-bytes",
    approvedEditionAssetHashesVerified: true,
    approvedEditionApplicationSourceWired: false,
    canonicalDonorState: "pending-universal-common-core",
    canonicalDonorManifestPath: null,
    canonicalDonorManifestSha256: null,
    canonicalDonorCommit: null,
    commonCoreBindingVerified: false,
    assetHashesVerified: false,
    approvedPalette: ["#00D9FF", "#2671FF", "#744CFF"],
    paletteApplied: false,
    iconIntegrated: false,
  });
  assert.deepEqual(contract.viewports, [
    { id: "desktop", width: 1440, height: 900 },
    { id: "tablet", width: 760, height: 900 },
    { id: "mobile", width: 390, height: 844 },
  ]);
  assert.deepEqual(contract.locales.map((locale) => locale.id), ["en", "zh-CN"]);
  assert.deepEqual(contract.routes, {
    overview: "/sim",
    setup: "/desktop/setup",
    forbiddenPrefixes: ["/lab", "/field", "/hitl", "/hardware"],
    blockedDestination: "/sim",
  });
  assert.equal(contract.receipt.requiredCaseCount, 6);
  assert.equal(Object.values(contract.nonClaims).every((value) => value === false), true);

  const branchContract = JSON.parse(
    await readFile(resolveRepoFile("distribution/branch-contracts/software-sim.v1.json"), "utf8"),
  );
  assert.equal(contract.source.branch, "codex/software-sim");
  assert.equal(contract.source.commonCoreCommit, branchContract.syncBaseline.commonCoreCommit);
  assert.equal(contract.source.commonCoreHash, branchContract.syncBaseline.commonCoreHash);
  assert.equal(contract.source.refs.length, 16);
  for (const ref of contract.source.refs) {
    assertExactKeys(ref, ["path", "sha256"], `source ref ${ref.path}`);
    assert.match(ref.sha256, /^[0-9a-f]{64}$/);
    assert.equal(await sha256File(resolveRepoFile(ref.path)), ref.sha256, `${ref.path} SHA-256 drifted`);
  }

  const overlay = JSON.parse(
    await readFile(resolveRepoFile("distribution/sim/desktop/tauri.sim.conf.json"), "utf8"),
  );
  assert.equal(overlay.productName, contract.productIdentity.displayName);
  assert.equal(overlay.app.windows[0].minWidth, 390);

  const python = process.env.PYTHON || "python";
  const donorTool = resolveRepoFile("distribution/sim/tools/sim_brand_donor.py");
  execFileSync(python, [
    donorTool,
    "verify-intake",
    "--repo-root",
    repoRoot,
    resolveRepoFile(contract.brandDonor.intakePath),
  ], { cwd: repoRoot, stdio: "pipe" });
  execFileSync(python, [
    donorTool,
    "verify-approved-assets",
    "--repo-root",
    repoRoot,
    resolveRepoFile(contract.brandDonor.approvedEditionAssetManifestPath),
  ], { cwd: repoRoot, stdio: "pipe" });
  if (donorManifestArgument) {
    assert.equal(typeof donorManifestArgument, "string", "--donor-manifest requires a path");
    const donorManifestPath = path.resolve(repoRoot, donorManifestArgument);
    assert(
      donorManifestPath.startsWith(`${repoRoot}${path.sep}`),
      "donor manifest path must stay inside repository",
    );
    execFileSync(python, [
      donorTool,
      "verify-donor",
      "--repo-root",
      repoRoot,
      "--intake",
      resolveRepoFile(contract.brandDonor.intakePath),
      "--require-working-tree-assets",
      donorManifestPath,
    ], { cwd: repoRoot, stdio: "pipe" });
    throw new Error("canonical donor verified but visual contract remains pending integration");
  }
  return contract;
}

const contract = await loadAndValidateContract();
const contractSha256 = await sha256File(contractPath);

if (contractOnly) {
  process.stdout.write(`${JSON.stringify({
    status: "pass",
    mode: "GREEN-contract-only",
    contract: path.relative(repoRoot, contractPath).replaceAll("\\", "/"),
    contractSha256,
    browserStarted: false,
    productionBuildExecuted: false,
  }, null, 2)}\n`);
  process.exit(0);
}

assert.equal(git("branch", "--show-current"), contract.source.branch, "wrong Sim branch");
assert.equal(git("status", "--short"), "", "YELLOW visual acceptance requires a clean source tree");

const port = Number(args.get("--port") || 5198);
assert(Number.isInteger(port) && port > 1024 && port < 65536, "invalid local Vite port");
const host = "127.0.0.1";
const origin = `http://${host}:${port}`;
const sourceCommit = git("rev-parse", "HEAD");
const outputRoot = path.resolve(
  repoRoot,
  String(
    args.get("--output")
      || `artifacts/test-runs/sim-frontend-visual-${sourceCommit.slice(0, 8)}`,
  ),
);
assert(outputRoot.startsWith(`${repoRoot}${path.sep}`), "output path must stay inside repository");

process.env.VITE_API_BASE_URL = `${origin}/api/v1`;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const frontendRequire = createRequire(path.join(frontendRoot, "package.json"));
const { createServer } = await import(pathToFileURL(frontendRequire.resolve("vite")).href);
const { chromium } = await import(pathToFileURL(frontendRequire.resolve("playwright")).href);

async function screenshot(page, caseId, surface) {
  const target = path.join(outputRoot, `${caseId}-${surface}.png`);
  await page.screenshot({ path: target, fullPage: true });
  return {
    path: path.relative(repoRoot, target).replaceAll("\\", "/"),
    sha256: await sha256File(target),
  };
}

async function verifyOverview(page, testCase) {
  await page.goto(`${origin}${contract.routes.overview}?docsPreview=1`, {
    waitUntil: "networkidle",
  });
  await page.locator(".sim-overview-page").waitFor();
  const metrics = await page.locator(".sim-overview-page").evaluate((element, expected) => {
    const interactive = Array.from(
      document.querySelectorAll("a, button, input, select, [role='button'], [role='radio']"),
    );
    return {
      title: element.querySelector("h1")?.textContent?.trim(),
      previewStatus: element.querySelector(".sim-overview-state > span")?.textContent?.trim(),
      capabilityCount: element.querySelectorAll(".sim-capability-grid > li").length,
      dependencyCount: element.querySelectorAll(".sim-dependency-list > li").length,
      externalCount: Array.from(element.querySelectorAll(".sim-dependency-list > li > span"))
        .filter((item) => item.textContent?.trim()).length,
      capabilityListLabel: element.querySelector(".sim-capability-grid")?.getAttribute("aria-label"),
      dependencyListLabel: element.querySelector(".sim-dependency-list")?.getAttribute("aria-label"),
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      forbiddenInteractiveCount: interactive.filter((item) => {
        const signature = [
          item.textContent,
          item.getAttribute("aria-label"),
          item.getAttribute("href"),
          item.getAttribute("value"),
        ].filter(Boolean).join(" ");
        return /(?:^|[\s/])(lab|field|hitl|hardware)(?:$|[\s/?-])/i.test(signature);
      }).length,
      setupHref: element.querySelector(".sim-setup-preview a")?.getAttribute("href"),
      expected,
    };
  }, testCase.locale);
  assert.equal(metrics.title, testCase.locale.overviewTitle);
  assert.equal(metrics.previewStatus, testCase.locale.previewStatus);
  assert.equal(metrics.capabilityCount, 4);
  assert.equal(metrics.dependencyCount, 2);
  assert.equal(metrics.externalCount, 2);
  assert.equal(metrics.capabilityListLabel, testCase.locale.capabilityList);
  assert.equal(metrics.dependencyListLabel, testCase.locale.dependencyList);
  assert.equal(metrics.documentScrollWidth, metrics.documentWidth);
  assert.equal(metrics.forbiddenInteractiveCount, 0);
  assert.equal(metrics.setupHref, contract.routes.setup);
  const image = await screenshot(page, testCase.id, "overview");

  const setupLink = page.getByRole("link", { name: testCase.locale.setupLink });
  await setupLink.focus();
  assert.equal(await setupLink.evaluate((element) => element === document.activeElement), true);
  await Promise.all([
    page.waitForURL((url) => url.pathname === contract.routes.setup),
    page.keyboard.press("Enter"),
  ]);
  return { ...metrics, keyboardSetupNavigation: true, image };
}

async function verifySetup(page, testCase) {
  const panel = page.locator(".distribution-setup-panel-setup");
  await panel.waitFor();
  const metrics = await panel.evaluate((element, productName) => ({
    edition: element.getAttribute("data-edition"),
    capabilityBoundary: element.getAttribute("data-capability-boundary"),
    canApply: element.getAttribute("data-can-apply"),
    lockedIdentity: element.querySelector(".distribution-sim-locked-edition strong")
      ?.textContent?.trim(),
    controllerControlCount: element.querySelectorAll("select[id$='-controller']").length,
    optionalModuleControlCount: element.querySelectorAll(".distribution-optional-modules input").length,
    commandButtonCount: element.querySelectorAll("button").length,
    documentWidth: document.documentElement.clientWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    productName,
  }), contract.productIdentity.displayName);
  assert.equal(metrics.edition, "sim");
  assert.equal(metrics.capabilityBoundary, "simulation-only");
  assert.equal(metrics.canApply, "false");
  assert.equal(metrics.lockedIdentity, contract.productIdentity.displayName);
  assert.equal(metrics.controllerControlCount, 0);
  assert.equal(metrics.optionalModuleControlCount, 0);
  assert.equal(metrics.commandButtonCount, 0);
  assert.equal(metrics.documentScrollWidth, metrics.documentWidth);
  return { ...metrics, image: await screenshot(page, testCase.id, "setup") };
}

async function verifyBlockedRoutes(page, testCase) {
  const results = [];
  for (const prefix of contract.routes.forbiddenPrefixes) {
    await page.goto(`${origin}${prefix}/acceptance-probe`, { waitUntil: "networkidle" });
    const alert = page.getByRole("alert");
    await alert.waitFor();
    const current = new URL(page.url());
    assert.equal(current.pathname, contract.routes.blockedDestination);
    assert(current.searchParams.has("blocked"));
    results.push({ prefix, destination: current.pathname, blocked: true });
  }
  return {
    routes: results,
    image: await screenshot(page, testCase.id, "blocked-route"),
  };
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  root: frontendRoot,
  server: { host, port, strictPort: true },
  logLevel: "error",
});
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];
let failure;

try {
  for (const viewport of contract.viewports) {
    for (const locale of contract.locales) {
      const testCase = {
        id: `${viewport.id}-${locale.id}`,
        viewport,
        locale,
      };
      const context = await browser.newContext({ viewport });
      await context.addInitScript((localeId) => {
        window.localStorage.setItem("drone-dream:locale", localeId);
      }, locale.id);
      await context.route("**/api/v1/**", (route) => route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Offline Sim visual acceptance fixture" }),
      }));
      const page = await context.newPage();
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      const result = { case: testCase };
      try {
        result.overview = await verifyOverview(page, testCase);
        result.setup = await verifySetup(page, testCase);
        result.blockedRoutes = await verifyBlockedRoutes(page, testCase);
        assert.deepEqual(pageErrors, []);
        result.status = "pass";
      } catch (error) {
        result.status = "fail";
        result.error = error instanceof Error ? error.stack : String(error);
        failure = error;
      }
      results.push(result);
      await context.close();
      if (failure) break;
    }
    if (failure) break;
  }
} finally {
  await browser.close();
  await server.close();
}

const receipt = {
  schemaVersion: 1,
  kind: contract.receipt.kind,
  editionId: contract.editionId,
  sourceCommit,
  sourceTreeState: "clean",
  branch: contract.source.branch,
  commonCoreCommit: contract.source.commonCoreCommit,
  commonCoreHash: contract.source.commonCoreHash,
  contract: {
    path: path.relative(repoRoot, contractPath).replaceAll("\\", "/"),
    sha256: contractSha256,
  },
  brandDonor: contract.brandDonor,
  executionClass: contract.executionClass,
  browser: contract.receipt.browser,
  networkPolicy: contract.networkPolicy,
  apiKeyReadByTool: false,
  productionBuildExecuted: false,
  generatedAt: new Date().toISOString(),
  cases: results,
  status: failure ? "fail" : "pass",
};
const receiptPath = path.join(outputRoot, "sim-frontend-visual-acceptance-receipt.json");
await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({
  status: receipt.status,
  sourceCommit,
  completedCases: results.length,
  receipt: path.relative(repoRoot, receiptPath).replaceAll("\\", "/"),
  receiptSha256: await sha256File(receiptPath),
}, null, 2)}\n`);
if (failure) throw failure;
