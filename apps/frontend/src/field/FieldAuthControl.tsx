import { useState } from "react";
import { LogIn, LogOut } from "lucide-react";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import { LauncherAccountForm } from "../components/LauncherAccountForm";
import type { FieldLocale } from "./catalog";

const COPY = {
  en: {
    enter: "Enter the tuning platform",
    signIn: "Sign in to DroneDream · FIELD",
    signInAndEnter: "Sign in and enter the tuning platform",
    signOut: "Sign out of DroneDream · FIELD",
    waiting: "Waiting for browser authorization",
    adopting: "Opening Field session",
    signedIn: "Signed in as",
    unavailable: "Field sign-in is unavailable in this build.",
    failed: "Field sign-in could not be completed.",
  },
  "zh-CN": {
    enter: "进入调优平台",
    signIn: "登录 DroneDream · FIELD",
    signInAndEnter: "登录并进入调优平台",
    signOut: "退出 DroneDream · FIELD",
    waiting: "等待浏览器授权",
    adopting: "正在建立 Field 会话",
    signedIn: "已登录",
    unavailable: "当前版本未配置 Field 登录。",
    failed: "Field 登录未完成。",
  },
} as const;

interface FieldAuthControlProps {
  locale: FieldLocale;
  launcher?: boolean;
  launcherReady?: boolean;
  onAuthenticated?: () => void;
}

export function FieldAuthControl({ locale, launcher = false, launcherReady = true, onAuthenticated }: FieldAuthControlProps) {
  const { account, signOut } = useAuthOrLocal();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const copy = COPY[locale];
  return <div className={`field-auth-control${launcher ? " field-auth-control-launcher" : ""}`} data-authority="false">
    {account && launcher ? <button type="button" disabled={!launcherReady} onClick={onAuthenticated} aria-label={copy.enter}><LogIn aria-hidden="true" />{copy.enter}</button>
      : account ? <button type="button" aria-label={copy.signOut} onClick={() => { setError(""); void signOut().catch(() => setError(copy.failed)); }}><LogOut aria-hidden="true" />{account.displayName}</button>
      : <button type="button" aria-label={copy.signIn} onClick={() => setOpen(true)}><LogIn aria-hidden="true" />{copy.signIn}</button>}
    <span className="field-auth-status" role={error ? "alert" : undefined}>{error}</span>
    {open && !account ? <div className="launcher-settings-backdrop" onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
      <div role="dialog" aria-modal="true" aria-label={copy.signIn} className="launcher-progress-panel">
        <button type="button" className="launcher-auth-secondary" onClick={() => setOpen(false)}>{locale === "en" ? "Close" : "关闭"}</button>
        <LauncherAccountForm locale={locale} onAuthenticated={() => { setOpen(false); if (launcherReady) onAuthenticated?.(); }} />
      </div>
    </div> : null}
  </div>;
}
