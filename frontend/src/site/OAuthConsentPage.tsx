import { useEffect, useState } from "react";

import type { DroneDreamAccount } from "../features/auth/AuthContext";
import { supabaseClient } from "../features/auth/supabaseClient";
import type { Locale } from "../i18n/I18nProvider";
import {
  desktopEditionForRedirectUri,
  isAllowedDesktopCallback,
  isAllowedDesktopRedirectUri,
} from "./oauthConsentPolicy";

interface AuthorizationDetails {
  authorization_id: string;
  redirect_uri: string;
  scope: string;
  client: {
    name: string;
    uri: string;
    logo_uri: string;
  };
  user: {
    id: string;
    email: string;
  };
}

interface OAuthConsentPageProps {
  locale: Locale;
  account: DroneDreamAccount | null;
  authConfigured: boolean;
  authLoading: boolean;
  onRequireSignIn: () => void;
  onRequireRegistration: () => void;
  onSwitchAccount: () => void;
}

const copy = {
  en: {
    eyebrow: "SECURE DESKTOP SIGN-IN",
    title: "Continue to DroneDream",
    invalidRequest: "This desktop sign-in request is missing or invalid. Return to the app and try again.",
    unavailable: "DroneDream account sign-in is not configured on this website deployment.",
    signInBody: "Sign in in this browser to verify your email and password before authorizing the desktop app.",
    signIn: "Sign in and continue",
    register: "New to DroneDream? Create an account",
    loading: "Checking the desktop sign-in request…",
    requestFailed: "The desktop sign-in request could not be verified. Return to the app and try again.",
    signedInAs: "Signed in as",
    verifiedSession: "This browser has already verified this account.",
    switchAccount: "Not your account? Switch account",
    wantsAccess: "wants to access your DroneDream account.",
    permissions: "Requested access",
    permissionAccount: "Confirm your account identity",
    permissionSession: "Create a session for this desktop edition",
    standardFields: "Standard account fields",
    localReturn: "After approval, this browser returns only to the requesting app on this computer.",
    approve: "Approve and return to the app",
    deny: "Cancel sign-in",
    working: "Completing sign-in…",
  },
  "zh-CN": {
    eyebrow: "安全桌面端登录",
    title: "继续登录 DroneDream",
    invalidRequest: "本次桌面端登录请求缺失或无效。请返回软件后重新尝试。",
    unavailable: "当前网站部署尚未配置 DroneDream 账户登录。",
    signInBody: "请先在浏览器中输入邮箱与密码完成身份验证，再授权桌面软件。",
    signIn: "登录并继续",
    register: "还没有 DroneDream 账号？立即注册",
    loading: "正在核对桌面端登录请求…",
    requestFailed: "无法验证本次桌面端登录请求。请返回软件后重新尝试。",
    signedInAs: "当前登录账户",
    verifiedSession: "当前浏览器已完成该账户的身份验证。",
    switchAccount: "不是您的账户？切换账户",
    wantsAccess: "正在申请访问您的 DroneDream 账户。",
    permissions: "申请的权限",
    permissionAccount: "确认您的账户身份",
    permissionSession: "为当前桌面端版本创建独立会话",
    standardFields: "标准账户字段",
    localReturn: "授权后，浏览器只会回到本机上发起请求的 DroneDream 软件。",
    approve: "同意并返回软件",
    deny: "取消登录",
    working: "正在完成登录…",
  },
} as const;

function authorizationIdFromLocation(): string | null {
  const value = new URLSearchParams(window.location.search).get("authorization_id")?.trim();
  if (!value || value.length < 8 || value.length > 512) return null;
  return /^[A-Za-z0-9._~-]+$/u.test(value) ? value : null;
}

function redirectToDesktop(value: string): void {
  if (!isAllowedDesktopCallback(value)) {
    throw new Error("The authorization server returned an unapproved desktop callback.");
  }
  window.location.assign(value);
}

export function OAuthConsentPage({
  locale,
  account,
  authConfigured,
  authLoading,
  onRequireSignIn,
  onRequireRegistration,
  onSwitchAccount,
}: OAuthConsentPageProps) {
  const text = copy[locale];
  const authorizationId = authorizationIdFromLocation();
  const [details, setDetails] = useState<AuthorizationDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!authorizationId || !account || !supabaseClient) {
      setDetails(null);
      return undefined;
    }
    let active = true;
    setError(null);
    setPending(true);
    void supabaseClient.auth.oauth.getAuthorizationDetails(authorizationId)
      .then(({ data, error: requestError }) => {
        if (!active) return;
        if (requestError || !data) throw requestError ?? new Error("Authorization request missing.");
        if ("redirect_url" in data) {
          redirectToDesktop(data.redirect_url);
          return;
        }
        if (
          data.authorization_id !== authorizationId
          || !isAllowedDesktopRedirectUri(data.redirect_uri)
        ) {
          throw new Error("The authorization request does not match a DroneDream desktop edition.");
        }
        setDetails(data);
      })
      .catch(() => {
        if (active) setError(text.requestFailed);
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [account, authorizationId, text.requestFailed]);

  const decide = async (approved: boolean) => {
    if (!authorizationId || !details || !supabaseClient || pending) return;
    setPending(true);
    setError(null);
    try {
      const response = approved
        ? await supabaseClient.auth.oauth.approveAuthorization(
          authorizationId,
          { skipBrowserRedirect: true },
        )
        : await supabaseClient.auth.oauth.denyAuthorization(
          authorizationId,
          { skipBrowserRedirect: true },
        );
      if (response.error || !response.data) {
        throw response.error ?? new Error("Authorization response missing.");
      }
      redirectToDesktop(response.data.redirect_url);
    } catch {
      setError(text.requestFailed);
      setPending(false);
    }
  };

  const edition = details
    ? desktopEditionForRedirectUri(details.redirect_uri)
    : null;
  const scopes = details?.scope.split(/\s+/u).filter(Boolean) ?? [];

  return (
    <section className="site-oauth-consent" aria-labelledby="oauth-consent-title">
      <div className="site-oauth-card">
        <p className="site-eyebrow">{text.eyebrow}</p>
        <h1 id="oauth-consent-title">{text.title}</h1>
        {!authorizationId ? <div className="site-oauth-error" role="alert">{text.invalidRequest}</div> : null}
        {authorizationId && !authConfigured ? (
          <div className="site-oauth-error" role="alert">{text.unavailable}</div>
        ) : null}
        {authorizationId && authConfigured && (authLoading || pending) && !details ? (
          <div className="site-oauth-loading" role="status">{text.loading}</div>
        ) : null}
        {authorizationId && authConfigured && !authLoading && !account ? (
          <div className="site-oauth-sign-in">
            <p>{text.signInBody}</p>
            <button type="button" className="site-button site-button-primary" onClick={onRequireSignIn}>
              {text.signIn}
            </button>
            <button
              type="button"
              className="site-oauth-text-button"
              onClick={onRequireRegistration}
            >
              {text.register}
            </button>
          </div>
        ) : null}
        {details && account && edition ? (
          <div className="site-oauth-request">
            <div className="site-oauth-product">
              <span>{edition.edition}</span>
              <strong>{details.client.name || edition.product}</strong>
              <p>{text.wantsAccess}</p>
            </div>
            <dl className="site-oauth-facts">
              <div className="site-oauth-identity">
                <dt>{text.signedInAs}</dt>
                <dd>
                  <strong>{account.email ?? account.displayName}</strong>
                  <span>{text.verifiedSession}</span>
                  <button type="button" onClick={onSwitchAccount}>
                    {text.switchAccount}
                  </button>
                </dd>
              </div>
              <div>
                <dt>{text.permissions}</dt>
                <dd>
                  <ul>
                    <li>{text.permissionAccount}</li>
                    <li>{text.permissionSession}</li>
                  </ul>
                  <div className="site-oauth-scopes" aria-label={text.standardFields}>
                    <span>{text.standardFields}</span>
                    {scopes.map((scope) => <code key={scope}>{scope}</code>)}
                  </div>
                </dd>
              </div>
            </dl>
            <p className="site-oauth-local-return">{text.localReturn}</p>
            <div className="site-oauth-actions">
              <button type="button" className="site-button site-button-primary" disabled={pending} onClick={() => void decide(true)}>
                {pending ? text.working : text.approve}
              </button>
              <button type="button" className="site-button site-button-ghost" disabled={pending} onClick={() => void decide(false)}>
                {text.deny}
              </button>
            </div>
          </div>
        ) : null}
        {error ? <div className="site-oauth-error" role="alert">{error}</div> : null}
      </div>
    </section>
  );
}
