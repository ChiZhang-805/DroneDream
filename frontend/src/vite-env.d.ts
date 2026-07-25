/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_GAZEBO_VIEWER_URL?: string;
  readonly VITE_RUNTIME_RELEASE_MANIFEST_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  readonly VITE_TURNSTILE_SITE_KEY?: string;
  readonly VITE_AUTH_GOOGLE_ENABLED?: "true" | "false";
  readonly VITE_AUTH_APPLE_ENABLED?: "true" | "false";
  readonly VITE_PUBLIC_DEMO_CONSOLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
