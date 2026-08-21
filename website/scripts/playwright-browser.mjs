import { existsSync } from "node:fs";

const browserOverrideVariable = "DRONEDREAM_AUDIT_BROWSER";

export const launchSiteBrowser = async (chromium, { disableGpu = false } = {}) => {
  const browserOverride = process.env[browserOverrideVariable]?.trim();
  if (browserOverride && !existsSync(browserOverride)) {
    throw new Error(`${browserOverrideVariable} does not point to an existing browser executable: ${browserOverride}`);
  }

  return chromium.launch({
    ...(browserOverride ? { executablePath: browserOverride } : {}),
    headless: true,
    args: [
      "--use-angle=swiftshader",
      "--enable-unsafe-swiftshader",
      ...(disableGpu ? ["--disable-gpu"] : []),
    ],
  });
};
