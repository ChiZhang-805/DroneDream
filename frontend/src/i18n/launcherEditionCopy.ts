import type { BrandEditionId } from "../brand/edition-brand.generated";

export type LauncherEditionCopy = {
  enWelcome: string;
  enReady: string;
  enOpen: string;
  enSignIn: string;
  zhWelcome: string;
  zhReady: string;
  zhOpen: string;
  zhSignIn: string;
};

const launcherCopyByEdition = {
  universal: {
    enWelcome: "Bring every DroneDream workflow together",
    enReady: "Your DroneDream workspace is ready",
    enOpen: "Open DroneDream workspace",
    enSignIn: "Sign in and enter DroneDream",
    zhWelcome: "统一进入 DroneDream 全部工作流",
    zhReady: "你的 DroneDream 工作区已经就绪",
    zhOpen: "进入 DroneDream 工作区",
    zhSignIn: "登录并进入 DroneDream",
  },
  sim: {
    enWelcome: "Build your flight simulation workspace",
    enReady: "Your simulation workspace is ready",
    enOpen: "Open simulation workspace",
    enSignIn: "Sign in and enter simulation workspace",
    zhWelcome: "构建你的飞行仿真工作区",
    zhReady: "你的仿真工作区已经就绪",
    zhOpen: "进入仿真工作区",
    zhSignIn: "登录并进入仿真工作区",
  },
  lab: {
    enWelcome: "Prepare your laboratory validation workspace",
    enReady: "Your laboratory workspace is ready",
    enOpen: "Open laboratory workspace",
    enSignIn: "Sign in and enter laboratory workspace",
    zhWelcome: "准备你的实验室验证工作区",
    zhReady: "你的实验室工作区已经就绪",
    zhOpen: "进入实验室工作区",
    zhSignIn: "登录并进入实验室工作区",
  },
  field: {
    enWelcome: "Prepare your field operations workspace",
    enReady: "Your field workspace is ready",
    enOpen: "Open field workspace",
    enSignIn: "Sign in and enter field workspace",
    zhWelcome: "准备你的现场运行工作区",
    zhReady: "你的现场工作区已经就绪",
    zhOpen: "进入现场工作区",
    zhSignIn: "登录并进入现场工作区",
  },
  autonomy: {
    enWelcome: "Build your autonomous flight workspace",
    enReady: "Your autonomous mission workspace is ready",
    enOpen: "Open autonomous mission workspace",
    enSignIn: "Sign in and enter autonomous mission workspace",
    zhWelcome: "构建你的自主飞行工作空间",
    zhReady: "你的自主任务工作区已经就绪",
    zhOpen: "进入自主任务工作区",
    zhSignIn: "登录并进入自主任务工作区",
  },
} satisfies Record<BrandEditionId, LauncherEditionCopy>;

export function launcherCopyForEdition(
  edition: BrandEditionId,
): LauncherEditionCopy {
  return launcherCopyByEdition[edition];
}
