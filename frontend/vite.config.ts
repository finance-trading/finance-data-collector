import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  build: {
    outDir: "static-dist",
    rollupOptions: {
      input: {
        index: resolve(root, "index.html"),
        company: resolve(root, "company.html"),
        graph: resolve(root, "graph.html"),
        layers: resolve(root, "layers.html"),
        research: resolve(root, "research.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
