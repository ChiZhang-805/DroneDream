import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));
const serializedRelease = process.env.DRONEDREAM_RELEASE_JSON;
if (serializedRelease) JSON.parse(serializedRelease);

export default defineConfig({
  plugins: [react()],
  define: serializedRelease
    ? { __DRONEDREAM_RELEASE__: serializedRelease }
    : {},
  build: {
    outDir: "site-dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 520,
    rollupOptions: {
      input: `${projectRoot}site.html`,
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
});
