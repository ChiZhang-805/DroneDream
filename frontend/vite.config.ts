import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
});
