import { fileURLToPath } from "node:url";

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectRoot, "");
  for (const required of [
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_PUBLISHABLE_KEY",
  ]) {
    if (!env[required]?.trim()) {
      throw new Error(`${required} is required for the authenticated console build.`);
    }
  }

  return {
    plugins: [react()],
    base: "/console/",
    define: {
      "import.meta.env.VITE_PUBLIC_DEMO_CONSOLE": JSON.stringify("true"),
      __DRONEDREAM_BUILD_EDITION__: JSON.stringify("universal"),
    },
    build: {
      outDir: "site-dist/console",
      emptyOutDir: false,
      chunkSizeWarningLimit: 510,
      rollupOptions: {
        input: `${projectRoot}index.html`,
        output: {
          manualChunks: {
            three: ["three"],
            "react-vendor": ["react", "react-dom", "react-router-dom"],
            "query-vendor": ["@tanstack/react-query"],
          },
        },
      },
    },
  };
});
