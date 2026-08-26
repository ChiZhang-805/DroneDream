import { fileURLToPath } from "node:url";

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));
const serializedRelease = process.env.DRONEDREAM_RELEASE_JSON;
if (serializedRelease) JSON.parse(serializedRelease);

export default defineConfig(({ mode, isPreview }) => {
  const env = loadEnv(mode, projectRoot, "");
  if (!isPreview) {
    for (const key of ["VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"]) {
      if (!env[key]?.trim()) {
        throw new Error(`${key} is required for the public website account flow.`);
      }
    }
  }

  return {
    plugins: [react()],
    define: {
      // The public website uses the shared/universal product surface. Defining
      // the edition here keeps shared brand and capability modules safe when
      // they are reached from the browser-only OAuth entry point.
      __DRONEDREAM_BUILD_EDITION__: JSON.stringify("universal"),
      ...(serializedRelease
        ? { __DRONEDREAM_RELEASE__: serializedRelease }
        : {}),
    },
    build: {
      outDir: "site-dist",
      emptyOutDir: true,
      chunkSizeWarningLimit: 520,
      rollupOptions: {
        input: {
          main: `${projectRoot}site.html`,
          product: `${projectRoot}product/index.html`,
          manual: `${projectRoot}manual/index.html`,
          pricing: `${projectRoot}pricing/index.html`,
          community: `${projectRoot}community/index.html`,
          organization: `${projectRoot}organization/index.html`,
          oauthConsent: `${projectRoot}oauth/consent/index.html`,
        },
        output: {
          manualChunks: {
            three: ["three"],
            "react-vendor": ["react", "react-dom"],
          },
        },
      },
    },
    server: {
      host: "127.0.0.1",
      port: 4174,
      fs: {
        allow: [".."],
      },
    },
    preview: {
      host: "127.0.0.1",
      port: 4174,
    },
  };
});
