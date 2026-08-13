import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));
const fieldBrandLockup = fileURLToPath(
  new URL("./src/field/FieldBrandLockup.tsx", import.meta.url),
);
const fieldI18nShim = fileURLToPath(
  new URL("./src/field/FieldI18nShim.tsx", import.meta.url),
);

export default defineConfig({
  plugins: [react()],
  // Field owns a real-device-only payload. The shared public directory also
  // contains Universal/SIM manuals, so copying it would reintroduce simulation
  // documentation into the Field installer even though no simulator executes.
  publicDir: false,
  resolve: {
    alias: [
      { find: "./BrandLockup", replacement: fieldBrandLockup },
      { find: "../i18n/I18nProvider", replacement: fieldI18nShim },
    ],
  },
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
    fs: {
      allow: [".."],
    },
  },
});
