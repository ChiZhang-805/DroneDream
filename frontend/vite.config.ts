import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const SUPPORTED_DESKTOP_EDITIONS = new Set(["universal", "sim", "lab"]);

export default defineConfig(() => {
  const edition = (process.env.VITE_DRONEDREAM_EDITION ?? "universal")
    .trim()
    .toLowerCase();
  if (!SUPPORTED_DESKTOP_EDITIONS.has(edition)) {
    throw new Error(`Unsupported shared desktop edition: ${edition}`);
  }

  return {
    plugins: [react()],
    // Replacing a dedicated compile-time symbol lets Rollup remove lazy route
    // imports owned by another product. Reading import.meta.env through a
    // runtime helper kept every edition page in every shared-core bundle.
    define: {
      __DRONEDREAM_BUILD_EDITION__: JSON.stringify(edition),
    },
    build: {
      // Three.js is intentionally kept behind the launcher's lazy boundary. Its
      // dedicated minified vendor chunk is ~500.1 kB (~125 kB gzip), so use a
      // narrow threshold that still catches accidental growth elsewhere.
      chunkSizeWarningLimit: 510,
      rollupOptions: {
        output: {
          manualChunks: {
            three: ["three"],
            "react-vendor": ["react", "react-dom", "react-router-dom"],
            "query-vendor": ["@tanstack/react-query"],
          },
        },
      },
    },
    server: {
      port: 5173,
      host: "127.0.0.1",
    },
  };
});
