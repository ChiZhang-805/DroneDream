import { useEffect, useRef, useState } from "react";
import { browserAuthConfiguration } from "../features/auth/supabaseClient";
import type { Locale } from "../i18n/I18nProvider";
import { parseDesktopProviderHandoff, rememberDesktopProviderPreference } from "./desktopProviderHandoff";

/** Carry a named provider into the existing native-owned PKCE consent flow. */
export function DesktopProviderHandoffPage({ locale }: { locale: Locale }) {
  const started = useRef(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const configuration = browserAuthConfiguration();
    const handoff = configuration
      ? parseDesktopProviderHandoff(window.location.href, configuration.supabaseUrl)
      : null;
    if (!handoff) { setFailed(true); return; }
    try {
      rememberDesktopProviderPreference(handoff.provider);
      window.location.replace(handoff.authorizeUrl);
    } catch {
      setFailed(true);
    }
  }, []);
  if (!failed) return null;
  const message = locale === "zh-CN"
    ? "无法开始本次快捷登录。请返回软件后重试。"
    : "This sign-in could not be started. Return to the app and try again.";
  return <section className="site-oauth-consent"><div className="site-oauth-card">
    <p role={failed ? "alert" : "status"}>{message}</p>
  </div></section>;
}
