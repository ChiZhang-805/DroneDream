/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_GAZEBO_VIEWER_URL?: string;
  readonly VITE_RUNTIME_RELEASE_MANIFEST_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  readonly VITE_MODEL_GATEWAY_URL?: string;
  readonly VITE_BILLING_CHECKOUT_URL?: string;
  readonly VITE_TURNSTILE_SITE_KEY?: string;
  readonly VITE_AUTH_GOOGLE_ENABLED?: "true" | "false";
  readonly VITE_AUTH_APPLE_ENABLED?: "true" | "false";
  readonly VITE_DESKTOP_VISUAL_QA?: "true" | "false";
  readonly VITE_PUBLIC_DEMO_CONSOLE?: string;
  readonly VITE_DRONEDREAM_SOURCE_COMMIT?: string;
  readonly VITE_DRONEDREAM_EDITION?: "universal" | "sim" | "lab" | "field";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __DRONEDREAM_BUILD_EDITION__: "universal" | "sim" | "lab" | "field";
