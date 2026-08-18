import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputRoot = path.join(frontendRoot, "node_modules", ".cache", "autonomy-mission-entry");
const screenshotPath = path.join(outputRoot, "overview-conversation-1440x900.png");
const host = "127.0.0.1";
const port = 5196;
const origin = `http://${host}:${port}`;

process.env.VITE_API_BASE_URL = origin;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "true";
process.env.VITE_SUPABASE_URL = "https://local-build.invalid";
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = "local-build-placeholder";

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.console.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host, port, strictPort: true },
});
let browser;

try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
  await context.addInitScript(() => {
    window.localStorage.setItem("dronedream:universal-workspace:v2", "universal");
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
  });
  const page = await context.newPage();
  await page.goto(`${origin}/console/autonomy`, { waitUntil: "networkidle" });
  if (await page.locator(".autonomy-command-hero-icon").count() !== 1) {
    throw new Error("Fresh Overview must preserve the mission hero before the first message.");
  }
  if (await page.locator(".autonomy-command-examples > button").count() !== 3) {
    throw new Error("Fresh Overview must preserve all three mission examples.");
  }
  await page.evaluate(async () => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
    let storageKey = Object.keys(window.localStorage).find((key) => key.startsWith("dronedream:autonomy-workspace:v2:"));
    if (!storageKey) {
      const store = await import("/console/src/features/autonomy/workspaceStore.ts");
      store.saveAutonomyWorkspace("local", "universal", store.defaultAutonomyWorkspace());
      storageKey = Object.keys(window.localStorage).find((key) => key.startsWith("dronedream:autonomy-workspace:v2:"));
    }
    if (!storageKey) throw new Error("Autonomy workspace storage could not be initialized.");
    const workspace = JSON.parse(window.localStorage.getItem(storageKey));
    workspace.mapPack = {
      ...workspace.mapPack,
      name: "School Map",
      status: "qualified",
      calibrated: true,
      compilerSceneId: "school-campus-v1",
      confidencePercent: 100,
    };
    const nodeSpecs = [
      ["preflight-pack-identity", "绑定机型、固件和控制接口", "mission_executive", "critical", []],
      ["preflight-sensors", "验证传感器标定、时间同步和数据流", "perception", "critical", ["preflight-pack-identity"]],
      ["preflight-flight-envelope", "检查质量、重心、推力、电量与制动包络", "mission_executive", "critical", ["preflight-sensors"]],
      ["world-map-binding", "绑定地图坐标、语义实体与地理围栏", "global_planner", "high", ["preflight-flight-envelope"]],
      ["world-localization", "建立定位并初始化动态障碍世界模型", "perception", "critical", ["world-map-binding"]],
      ["plan-global-corridor", "生成主路线走廊和载荷返航备选路线", "global_planner", "high", ["world-localization"]],
      ["mission-01-takeoff-observe", "起飞前刷新局部感知", "perception", "high", ["plan-global-corridor"]],
      ["mission-01-takeoff-plan", "生成起飞轨迹段", "local_planner", "high", ["mission-01-takeoff-observe"]],
      ["mission-01-takeoff-qualify", "验证起飞轨迹动力学与安全策略", "mission_executive", "critical", ["mission-01-takeoff-plan"]],
      ["mission-01-takeoff-execute", "从三楼办公室起飞", "px4_bridge", "high", ["mission-01-takeoff-qualify"]],
      ["mission-01-takeoff-verify", "确认起飞完成证据", "mission_executive", "medium", ["mission-01-takeoff-execute"]],
      ["mission-02-transit-observe", "更新人员、楼梯与自由空间", "perception", "high", ["mission-01-takeoff-verify"]],
      ["mission-02-transit-plan", "规划通过楼梯的局部轨迹", "local_planner", "high", ["mission-02-transit-observe"]],
      ["mission-02-transit-qualify", "检查净空、制动距离和能量", "mission_executive", "high", ["mission-02-transit-plan"]],
      ["mission-02-transit-execute", "飞往外卖柜 7 号台", "local_planner", "high", ["mission-02-transit-qualify"]],
      ["mission-02-transit-verify", "确认到达目标点", "mission_executive", "medium", ["mission-02-transit-execute"]],
      ["mission-03-pickup-execute", "稳定悬停并取走咖啡", "payload_controller", "high", ["mission-02-transit-verify"]],
      ["mission-03-pickup-recompute-envelope", "确认载荷并重新计算返航包络", "mission_executive", "critical", ["mission-03-pickup-execute"]],
      ["mission-04-return-plan", "使用满载包络规划返航", "global_planner", "high", ["mission-03-pickup-recompute-envelope"]],
      ["postflight-state", "确认降落、解锁并关闭控制权限", "px4_bridge", "critical", ["mission-04-return-plan"]],
      ["postflight-evidence", "封存任务、异常、决策与回放证据", "mission_executive", "low", ["postflight-state"]],
    ];
    const nodes = nodeSpecs.map(([taskId, label, executor, risk, dependsOn], index) => ({
      task_id: taskId,
      label,
      status: index === 0 ? "ready" : "pending",
      depends_on: dependsOn,
      executor,
      risk,
      max_retries: risk === "critical" ? 1 : 2,
      timeout_s: 30,
      fallback: risk === "critical" ? "abort" : "hold",
      expected_output: "Task-specific verified output",
      completion_evidence: ["pose.trace", "safety.acceptance", "task.result"],
      inserted_by: "compiler",
    }));
    workspace.mission = {
      ...workspace.mission,
      intent: "从三楼办公室起飞，到外卖柜 7 号台取咖啡，然后避开人员并返回办公室。",
      planningBrief: "已将办公室、楼梯和外卖柜 7 号台绑定到地图语义实体，并生成满载返航备选路线。",
      conversationId: "conversation-browser-verification",
      messages: [
        {
          id: "user-browser-verification",
          role: "user",
          content: "从三楼办公室起飞，到外卖柜 7 号台取咖啡，然后避开人员并返回办公室。",
          createdAt: new Date().toISOString(),
          planContractId: null,
        },
        {
          id: "assistant-browser-verification",
          role: "assistant",
          content: "我已经绑定当前无人机和 School Map，并生成了可审阅的任务计划。执行前会依次验证传感器、质量包络、地图坐标和动态障碍物。",
          createdAt: new Date().toISOString(),
          planContractId: "mission-browser-verification",
        },
      ],
      aircraftProfileId: workspace.aircraft.id,
      mapPackId: workspace.mapPack.id,
      compiledPlan: {
        schemaVersion: 1,
        source: "backend",
        contractId: "mission-browser-verification",
        sceneId: "school-campus-v1",
        sceneName: "School Map",
        feasible: true,
        readiness: "simulation_ready",
        canExecute: true,
        perceptionMode: "fusion",
        steps: [],
        taskGraph: {
          schema_version: "dronedream.autonomy.task-graph.v1",
          revision: 1,
          nodes,
          active_node_ids: ["preflight-pack-identity"],
          change_reason: "compiled",
        },
        issues: [],
        metrics: {
          routeLengthM: 86.4,
          verticalTravelM: 14.8,
          estimatedDurationS: 112,
          minimumClearanceM: 0.92,
          launchMassKg: 1.55,
          postPickupMassKg: 1.9,
          postPickupThrustToWeight: 2.09,
          brakingDistanceM: 0.62,
        },
        immutableSafetyRules: ["The model cannot emit actuator commands."],
        compiledAt: new Date().toISOString(),
      },
      updatedAt: new Date().toISOString(),
    };
    window.localStorage.setItem(storageKey, JSON.stringify(workspace));
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.evaluate(() => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
  });
  const navigationLabels = await page.locator(".autonomy-section-switch a").allTextContents();
  if (navigationLabels.length !== 5 || navigationLabels.some((label) => label.trim() === "任务" || label.trim() === "Mission")) {
    throw new Error(`Unexpected Autonomy navigation: ${navigationLabels.join(" | ")}`);
  }
  if (await page.locator(".autonomy-command-page.is-conversation").count() !== 1) {
    throw new Error("Overview did not switch into the in-page conversation state.");
  }
  if (await page.locator(".autonomy-command-hero-icon, .autonomy-command-examples").count() !== 0) {
    throw new Error("Mission hero and examples must disappear after the first message.");
  }
  if (await page.locator(".autonomy-conversation-message.is-user").count() !== 1
    || await page.locator(".autonomy-conversation-message.is-assistant").count() !== 1) {
    throw new Error("Conversation must render one user message and one model reply.");
  }
  if (await page.locator(".autonomy-conversation-message.is-user .autonomy-conversation-avatar.is-user-account").count() !== 1) {
    throw new Error("The user message must render the account avatar boundary.");
  }
  if (await page.locator(".autonomy-conversation-message.is-assistant .autonomy-inline-plan").count() !== 1) {
    throw new Error("The generated plan must be nested inside the model reply.");
  }
  const conversationGeometry = await page.evaluate(() => {
    const composer = document.querySelector(".autonomy-command-composer")?.getBoundingClientRect();
    const modelAvatar = document.querySelector(".autonomy-conversation-message.is-assistant .autonomy-conversation-avatar")?.getBoundingClientRect();
    const userAvatar = document.querySelector(".autonomy-conversation-message.is-user .autonomy-conversation-avatar")?.getBoundingClientRect();
    return composer && modelAvatar && userAvatar ? {
      composerLeft: composer.left,
      composerRight: composer.right,
      modelLeft: modelAvatar.left,
      userRight: userAvatar.right,
    } : null;
  });
  if (!conversationGeometry
    || Math.abs(conversationGeometry.composerLeft - conversationGeometry.modelLeft) > 1
    || Math.abs(conversationGeometry.composerRight - conversationGeometry.userRight) > 1) {
    throw new Error(`Conversation avatar rails do not align with the composer: ${JSON.stringify(conversationGeometry)}`);
  }
  if (await page.locator(".autonomy-task-graph li").count() !== 21) {
    throw new Error("The persisted task graph did not render every task node.");
  }
  await page.locator(".assistant-add-button").click();
  if (await page.locator(".autonomy-context-asset input[type=radio]:checked").count() !== 2) {
    throw new Error("Aircraft and map must each expose one selected radio binding.");
  }
  await page.locator(".assistant-add-button").click();
  await page.screenshot({ path: screenshotPath, fullPage: false });
  await page.goto(`${origin}/console/autonomy/aircraft`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
  });
  if (await page.locator(".autonomy-asset-toolbar select").count() !== 1
    || await page.locator(".autonomy-asset-toolbar button").count() !== 1) {
    throw new Error("Aircraft library must expose saved-profile selection and new-profile creation.");
  }
  const aircraftOptions = await page.locator(".autonomy-asset-toolbar option").count();
  await page.locator(".autonomy-asset-toolbar button").click();
  if (await page.locator(".autonomy-asset-toolbar option").count() !== aircraftOptions + 1) {
    throw new Error("Creating a new aircraft did not preserve the prior saved profile.");
  }
  await page.goto(`${origin}/console/autonomy/maps`, { waitUntil: "networkidle" });
  await page.evaluate(() => {
    document.querySelector(".account-dialog-backdrop")?.remove();
    document.querySelectorAll("[inert]").forEach((element) => element.removeAttribute("inert"));
  });
  if (await page.locator(".autonomy-asset-toolbar select").count() !== 1
    || await page.locator(".autonomy-asset-toolbar button").count() !== 1) {
    throw new Error("Map library must expose saved-pack selection and new-pack creation.");
  }
  const mapOptions = await page.locator(".autonomy-asset-toolbar option").count();
  await page.locator(".autonomy-asset-toolbar button").click();
  if (await page.locator(".autonomy-asset-toolbar option").count() !== mapOptions + 1) {
    throw new Error("Creating a new map did not preserve the prior saved pack.");
  }
  await page.goto(`${origin}/console/autonomy/mission`, { waitUntil: "networkidle" });
  if (!page.url().endsWith("/console/autonomy")) {
    throw new Error(`Legacy Mission URL did not redirect to Overview: ${page.url()}`);
  }
  process.stdout.write(`${JSON.stringify({ navigationLabels, taskNodes: 21, screenshotPath }, null, 2)}\n`);
  await context.close();
} finally {
  await browser?.close();
  await server.close();
}
