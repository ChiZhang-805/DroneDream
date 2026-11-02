import { useEffect, useRef, useState } from "react";

import type { DroneDreamAccount } from "../features/auth/AuthContext";
import { supabaseClient } from "../features/auth/supabaseClient";
import type { Locale } from "../i18n/I18nProvider";
import {
  authorizationIdFromLocation,
  isAllowedDesktopCallback,
  isDesktopCallbackForRedirectUri,
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
  onDesktopRedirect?: (value: string) => void;
}

const copy = {
  en: {
    invalidRequest: "This desktop sign-in request is missing or invalid. Return to the app and try again.",
    unavailable: "DroneDream account sign-in is not configured on this website deployment.",
    requestFailed: "The desktop sign-in request could not be verified. Return to the app and try again.",
    retry: "Try again",
  },
  "zh-CN": {
    invalidRequest: "本次桌面端登录请求缺失或无效。请返回软件后重新尝试。",
    unavailable: "当前网站部署尚未配置 DroneDream 账户登录。",
    requestFailed: "无法验证本次桌面端登录请求。请返回软件后重新尝试。",
    retry: "重试",
  },
} as const;

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
  onDesktopRedirect = redirectToDesktop,
}: OAuthConsentPageProps) {
  const text = copy[locale];
  const authorizationId = authorizationIdFromLocation();
  const [details, setDetails] = useState<AuthorizationDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryCycle, setRetryCycle] = useState(0);
  const approvalAttemptRef = useRef<string | null>(null);
  const approvalIdentity = authorizationId && account
    ? `${authorizationId}:${account.id}`
    : null;

  useEffect(() => {
    if (!authorizationId || !account || !supabaseClient) {
      setDetails(null);
      return undefined;
    }
    let active = true;
    setDetails(null);
    setError(null);
    void supabaseClient.auth.oauth.getAuthorizationDetails(authorizationId)
      .then(({ data, error: requestError }) => {
        if (!active) return;
        if (requestError || !data) throw requestError ?? new Error("Authorization request missing.");
        if ("redirect_url" in data) {
          if (!isAllowedDesktopCallback(data.redirect_url)) {
            throw new Error("The authorization server returned an unapproved desktop callback.");
          }
          onDesktopRedirect(data.redirect_url);
          return;
        }
        if (
          data.authorization_id !== authorizationId
          || !isAllowedDesktopRedirectUri(data.redirect_uri)
          || data.user.id !== account.id
        ) {
          throw new Error("The authorization request does not match a DroneDream desktop edition.");
        }
        setDetails(data);
      })
      .catch(() => {
        if (active) setError(text.requestFailed);
      })
    return () => {
      active = false;
    };
  }, [account, authorizationId, onDesktopRedirect, retryCycle, text.requestFailed]);

  useEffect(() => {
    approvalAttemptRef.current = null;
  }, [approvalIdentity]);

  useEffect(() => {
    if (!authorizationId || !details || !account || !supabaseClient) return;
    if (
      details.authorization_id !== authorizationId
      || details.user.id !== account.id
    ) return;
    const attemptKey = `${authorizationId}:${account.id}:${retryCycle}`;
    if (approvalAttemptRef.current === attemptKey) return;
    approvalAttemptRef.current = attemptKey;
    let active = true;
    setError(null);
    void supabaseClient.auth.oauth.approveAuthorization(
      authorizationId,
      { skipBrowserRedirect: true },
    ).then(({ data, error: approvalError }) => {
      if (!active) return;
      if (approvalError || !data) {
        throw approvalError ?? new Error("Authorization response missing.");
      }
      if (!isDesktopCallbackForRedirectUri(
        data.redirect_url,
        details.redirect_uri,
      )) {
        throw new Error("The authorization server returned an unapproved desktop callback.");
      }
      onDesktopRedirect(data.redirect_url);
    }).catch(() => {
      if (!active) return;
      setError(text.requestFailed);
    });
    return () => {
      active = false;
    };
  }, [account, authorizationId, details, onDesktopRedirect, retryCycle, text.requestFailed]);

  if (authorizationId && authConfigured && !error) {
    return <div className="site-oauth-auth-stage" aria-hidden="true" />;
  }

  const message = !authorizationId
    ? text.invalidRequest
    : !authConfigured
      ? text.unavailable
      : error;
  return (
    <section className="site-oauth-consent">
      <div className="site-oauth-card">
        <div className="site-oauth-error" role="alert">{message}</div>
        {error ? (
          <button
            type="button"
            className="site-button site-button-primary"
            onClick={() => {
              // Revalidate the request before another approval; never reuse
              // details left by the failed cycle while the new lookup runs.
              setDetails(null);
              setRetryCycle((cycle) => cycle + 1);
            }}
          >
            {text.retry}
          </button>
        ) : null}
      </div>
    </section>
  );
}
