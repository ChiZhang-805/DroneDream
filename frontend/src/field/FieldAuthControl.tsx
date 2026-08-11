import { useEffect, useRef, useState } from "react";
import { LogIn, LogOut, LoaderCircle } from "lucide-react";

import {
  beginBrowserAuth,
  cancelBrowserAuth,
  clearBrowserAuthVault,
  isDesktopRuntime,
} from "../desktop/bridge";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import { adoptBrowserAuthSession } from "../features/auth/browserAuth";
import { activateDesktopAuthSession } from "../features/auth/desktopAuthActivation";
import { browserAuthConfiguration } from "../features/auth/supabaseClient";
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

type AuthStatus = "idle" | "waiting" | "adopting";

interface FieldAuthControlProps {
  locale: FieldLocale;
  launcher?: boolean;
  launcherReady?: boolean;
  onAuthenticated?: () => void;
}

export function FieldAuthControl({
  locale,
  launcher = false,
  launcherReady = true,
  onAuthenticated,
}: FieldAuthControlProps) {
  const { account, configured, signOut } = useAuthOrLocal();
  const [status, setStatus] = useState<AuthStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const browserAuthActive = useRef(false);
  const copy = COPY[locale];
  const available = configured && isDesktopRuntime();

  useEffect(() => () => {
    mounted.current = false;
    if (browserAuthActive.current) {
      void cancelBrowserAuth().catch(() => false);
    }
  }, []);

  const startSignIn = async () => {
    if (!available || status !== "idle") return;
    if (!browserAuthConfiguration()) {
      setError(copy.unavailable);
      return;
    }
    setError(null);
    setStatus("waiting");
    activateDesktopAuthSession();
    browserAuthActive.current = true;
    let sessionIssued = false;
    try {
      // Every click starts a fresh Field browser transaction. Browser cookies
      // may reduce credential entry, but no other edition session is restored.
      const session = await beginBrowserAuth({ locale });
      sessionIssued = true;
      if (!mounted.current) return;
      setStatus("adopting");
      await adoptBrowserAuthSession(session);
      if (mounted.current) onAuthenticated?.();
    } catch (cause) {
      if (sessionIssued) {
        await clearBrowserAuthVault().catch(() => false);
      }
      const message = cause instanceof Error ? cause.message : String(cause);
      if (mounted.current && !/cancelled/iu.test(message)) {
        setError(copy.failed);
      }
    } finally {
      browserAuthActive.current = false;
      if (mounted.current) setStatus("idle");
    }
  };

  const endSession = async () => {
    setError(null);
    try {
      await signOut();
    } catch {
      if (mounted.current) setError(copy.failed);
    }
  };

  return (
    <div
      className={`field-auth-control${launcher ? " field-auth-control-launcher" : ""}`}
      data-authority="false"
    >
      {account && launcher ? (
        <button
          type="button"
          disabled={!launcherReady}
          onClick={onAuthenticated}
          aria-label={copy.enter}
        >
          <LogIn aria-hidden="true" />
          <span>{copy.enter}</span>
        </button>
      ) : account ? (
        <button type="button" onClick={() => void endSession()} aria-label={copy.signOut}>
          <LogOut aria-hidden="true" />
          <span>{account.displayName}</span>
        </button>
      ) : (
        <button
          type="button"
          disabled={!available || status !== "idle" || (launcher && !launcherReady)}
          onClick={() => void startSignIn()}
          aria-label={launcher ? copy.signInAndEnter : copy.signIn}
        >
          {status === "idle"
            ? <LogIn aria-hidden="true" />
            : <LoaderCircle className="field-auth-spinner" aria-hidden="true" />}
          <span>{status === "waiting"
            ? copy.waiting
            : status === "adopting"
              ? copy.adopting
              : launcher
                ? copy.signInAndEnter
                : copy.signIn}</span>
        </button>
      )}
      <span className="field-auth-status" role={error ? "alert" : undefined} aria-live="polite">
        {error ?? (account ? `${copy.signedIn} ${account.displayName}` : "")}
      </span>
    </div>
  );
}
