import { fileURLToPath } from "node:url";

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));
const serializedRelease = process.env.DRONEDREAM_RELEASE_JSON;
if (serializedRelease) JSON.parse(serializedRelease);

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectRoot, "");
  for (const key of ["VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"]) {
    if (!env[key]?.trim()) {
      throw new Error(`${key} is required for the public website account flow.`);
    }
  }

  return {
    plugins: [react()],
    define: serializedRelease
      ? { __DRONEDREAM_RELEASE__: serializedRelease }
      : {},
    build: {
      outDir: "site-dist",
      emptyOutDir: true,
      chunkSizeWarningLimit: 520,
      rollupOptions: {
        input: {
          main: `${projectRoot}site.html`,
          manual: `${projectRoot}manual/index.html`,
          pricing: `${projectRoot}pricing/index.html`,
          community: `${projectRoot}community/index.html`,
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
    },
    preview: {
      host: "127.0.0.1",
      port: 4174,
    },
  };
});
