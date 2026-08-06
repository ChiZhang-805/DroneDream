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
    signIn: "Sign in to DroneDream · FIELD",
    signOut: "Sign out of DroneDream · FIELD",
    waiting: "Waiting for browser authorization",
    adopting: "Opening Field session",
    signedIn: "Signed in as",
    unavailable: "Field sign-in is unavailable in this build.",
    failed: "Field sign-in could not be completed.",
  },
  "zh-CN": {
    signIn: "登录 DroneDream · FIELD",
    signOut: "退出 DroneDream · FIELD",
    waiting: "等待浏览器授权",
    adopting: "正在建立 Field 会话",
    signedIn: "已登录",
    unavailable: "当前版本未配置 Field 登录。",
    failed: "Field 登录未完成。",
  },
} as const;

type AuthStatus = "idle" | "waiting" | "adopting";

export function FieldAuthControl({ locale }: { locale: FieldLocale }) {
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
    <div className="field-auth-control" data-authority="false">
      {account ? (
        <button type="button" onClick={() => void endSession()} aria-label={copy.signOut}>
          <LogOut aria-hidden="true" />
          <span>{account.displayName}</span>
        </button>
      ) : (
        <button
          type="button"
          disabled={!available || status !== "idle"}
          onClick={() => void startSignIn()}
          aria-label={copy.signIn}
        >
          {status === "idle"
            ? <LogIn aria-hidden="true" />
            : <LoaderCircle className="field-auth-spinner" aria-hidden="true" />}
          <span>{status === "waiting" ? copy.waiting : status === "adopting" ? copy.adopting : copy.signIn}</span>
        </button>
      )}
      <span className="field-auth-status" role={error ? "alert" : undefined} aria-live="polite">
        {error ?? (account ? `${copy.signedIn} ${account.displayName}` : "")}
      </span>
    </div>
  );
}
