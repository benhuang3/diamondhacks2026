import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { crx, defineManifest } from "@crxjs/vite-plugin";
import { readFileSync } from "node:fs";

const manifest = defineManifest(
  JSON.parse(readFileSync("./manifest.json", "utf-8")),
);

export default defineConfig({
  plugins: [react(), crx({ manifest })],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        popup: "src/popup.html",
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
