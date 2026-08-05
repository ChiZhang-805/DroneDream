import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));
const fieldBrandingRoot = fileURLToPath(
  new URL("../distribution/editions/field/branding", import.meta.url),
);

export default defineConfig({
  plugins: [react()],
  publicDir: fieldBrandingRoot,
  build: {
    outDir: "field-dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 300,
    rollupOptions: {
      input: `${projectRoot}field.html`,
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom"],
          "icon-vendor": ["lucide-react"],
        },
      },
    },
  },
  server: {
    port: 5174,
    host: "127.0.0.1",
  },
});
