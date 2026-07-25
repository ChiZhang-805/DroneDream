import { useEffect, useRef } from "react";

interface TurnstileOptions {
  sitekey: string;
  theme: "auto";
  callback: (token: string) => void;
  "error-callback": () => void;
  "expired-callback": () => void;
  "timeout-callback": () => void;
}

interface TurnstileApi {
  render: (container: HTMLElement, options: TurnstileOptions) => string;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_ID = "drone-dream-turnstile-script";
const SCRIPT_URL =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
let turnstilePromise: Promise<TurnstileApi> | null = null;

function loadTurnstile(): Promise<TurnstileApi> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (turnstilePromise) return turnstilePromise;

  turnstilePromise = new Promise<TurnstileApi>((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    const script = existing ?? document.createElement("script");
    const resolveApi = () => {
      if (window.turnstile) resolve(window.turnstile);
      else reject(new Error("Turnstile did not initialize."));
    };
    const rejectLoad = () => reject(new Error("Turnstile could not be loaded."));

    script.addEventListener("load", resolveApi, { once: true });
    script.addEventListener("error", rejectLoad, { once: true });
    if (!existing) {
      script.id = SCRIPT_ID;
      script.src = SCRIPT_URL;
      script.async = true;
      script.defer = true;
      document.head.append(script);
    }
  }).catch((error) => {
    turnstilePromise = null;
    throw error;
  });
  return turnstilePromise;
}

export function AuthCaptcha({
  siteKey,
  onTokenChange,
}: {
  siteKey: string;
  onTokenChange: (token: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    let widgetId: string | null = null;
    onTokenChange(null);
    void loadTurnstile()
      .then((api) => {
        if (!active || !containerRef.current) return;
        widgetId = api.render(containerRef.current, {
          sitekey: siteKey,
          theme: "auto",
          callback: (token) => {
            if (active) onTokenChange(token);
          },
          "error-callback": () => {
            if (active) onTokenChange(null);
          },
          "expired-callback": () => {
            if (active) onTokenChange(null);
          },
          "timeout-callback": () => {
            if (active) onTokenChange(null);
          },
        });
      })
      .catch(() => {
        if (active) onTokenChange(null);
      });

    return () => {
      active = false;
      onTokenChange(null);
      if (widgetId && window.turnstile) {
        window.turnstile.remove(widgetId);
      }
    };
  }, [onTokenChange, siteKey]);

  return <div className="auth-captcha" ref={containerRef} />;
}
