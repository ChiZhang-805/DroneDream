import { useEffect, useState } from "react";

import type { DroneDreamAccount } from "../features/auth/AuthContext";
import { supabaseClient } from "../features/auth/supabaseClient";
import {
  isExpectedOAuthScope,
  oauthClientRegistration,
  safeOAuthRedirectUrl,
  type OAuthClientRegistration,
} from "./oauthConsent";

interface ConsentDetails {
  authorizationId: string;
  registration: OAuthClientRegistration;
}

const copy = {
  en: {
    eyebrow: "DESKTOP SIGN IN",
    title: "Authorize this app",
    intro: "Continue only if you started sign in from this DroneDream app.",
    loading: "Checking this authorization request...",
    unavailable: "This authorization request cannot be completed here.",
    invalid: "This authorization request is invalid or no longer available.",
    scopes: "Account access",
    scopeValue: "Identity, email address, and profile",
    callback: "Return to",
    approve: "Authorize and return to app",
    deny: "Deny",
  },
  "zh-CN": {
    eyebrow: "桌面端登录",
    title: "授权此应用",
    intro: "仅在你刚刚从这个 DroneDream 应用发起登录时继续。",
    loading: "正在检查此授权请求...",
    unavailable: "无法在此处完成这个授权请求。",
    invalid: "此授权请求无效或已不可用。",
    scopes: "账号访问",
    scopeValue: "身份、邮箱地址与个人资料",
    callback: "返回",
    approve: "授权并返回应用",
    deny: "拒绝",
  },
} as const;

function defaultRedirect(url: string) {
  window.location.assign(url);
}

export function OAuthConsentPage({
  locale,
  account,
  authLoading,
  cloudActionsEnabled,
  authorizationId,
  onRequireSignIn,
  onRedirect = defaultRedirect,
}: {
  locale: "en" | "zh-CN";
  account: DroneDreamAccount | null;
  authLoading: boolean;
  cloudActionsEnabled: boolean;
  authorizationId: string | null;
  onRequireSignIn: (authorizationId: string) => void;
  onRedirect?: (url: string) => void;
}) {
  const strings = copy[locale];
  const [details, setDetails] = useState<ConsentDetails | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "redirecting">("loading");
  const [decisionPending, setDecisionPending] = useState(false);

  useEffect(() => {
    setDetails(null);
    setDecisionPending(false);
    if (!cloudActionsEnabled || !authorizationId) {
      setStatus("error");
      return undefined;
    }
    if (authLoading) {
      setStatus("loading");
      return undefined;
    }
    if (!account) {
      onRequireSignIn(authorizationId);
      return undefined;
    }
    if (!supabaseClient) {
      setStatus("error");
      return undefined;
    }

    let active = true;
    setStatus("loading");
    void supabaseClient.auth.oauth.getAuthorizationDetails(authorizationId)
      .then(({ data, error }) => {
        if (!active) return;
        if (error || !data) throw error ?? new Error("OAuth authorization details are missing");
        if ("redirect_url" in data) {
          const redirectUrl = safeOAuthRedirectUrl(data.redirect_url);
          if (!redirectUrl) throw new Error("OAuth redirect target is not registered");
          setStatus("redirecting");
          onRedirect(redirectUrl);
          return;
        }
        const registration = oauthClientRegistration(data.client.id, data.redirect_uri);
        if (
          data.authorization_id !== authorizationId
          || data.user.id !== account.id
          || !registration
          || !isExpectedOAuthScope(data.scope)
        ) {
          throw new Error("OAuth authorization details do not match the registered client");
        }
        setDetails({
          authorizationId,
          registration,
        });
        setStatus("ready");
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => {
      active = false;
    };
  }, [
    account,
    authLoading,
    authorizationId,
    cloudActionsEnabled,
    onRedirect,
    onRequireSignIn,
  ]);

  const decide = async (decision: "approve" | "deny") => {
    if (!details || decisionPending || !supabaseClient) return;
    setDecisionPending(true);
    try {
      const result = decision === "approve"
        ? await supabaseClient.auth.oauth.approveAuthorization(
            details.authorizationId,
            { skipBrowserRedirect: true },
          )
        : await supabaseClient.auth.oauth.denyAuthorization(
            details.authorizationId,
            { skipBrowserRedirect: true },
          );
      if (result.error || !result.data) {
        throw result.error ?? new Error("OAuth consent response is missing");
      }
      const redirectUrl = safeOAuthRedirectUrl(
        result.data.redirect_url,
        details.registration,
      );
      if (!redirectUrl) throw new Error("OAuth redirect target is not registered");
      setStatus("redirecting");
      onRedirect(redirectUrl);
    } catch {
      setStatus("error");
      setDecisionPending(false);
    }
  };

  return (
    <section
      className="site-auth-page"
      aria-labelledby="site-oauth-consent-title"
      data-oauth-consent="desktop"
    >
      <div className="site-auth-page-shell">
        <div className="site-auth-page-intro">
          <p className="site-eyebrow">{strings.eyebrow}</p>
          <h1 id="site-oauth-consent-title">{strings.title}</h1>
          <p>{strings.intro}</p>
        </div>
        <div className="site-auth-page-panel site-oauth-consent-panel">
          {status === "loading" || status === "redirecting" ? (
            <p role="status">{strings.loading}</p>
          ) : status === "error" || !details ? (
            <div className="site-auth-error" role="alert">
              {cloudActionsEnabled ? strings.invalid : strings.unavailable}
            </div>
          ) : (
            <>
              <strong className="site-oauth-client-name">
                {details.registration.displayName}
              </strong>
              <dl className="site-oauth-consent-details">
                <div>
                  <dt>{strings.scopes}</dt>
                  <dd>{strings.scopeValue}</dd>
                </div>
                <div>
                  <dt>{strings.callback}</dt>
                  <dd>{details.registration.displayName}</dd>
                </div>
              </dl>
              <div className="site-oauth-consent-actions">
                <button
                  type="button"
                  disabled={decisionPending}
                  onClick={() => void decide("approve")}
                >
                  {strings.approve}
                </button>
                <button
                  type="button"
                  disabled={decisionPending}
                  onClick={() => void decide("deny")}
                >
                  {strings.deny}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
