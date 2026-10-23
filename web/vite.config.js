import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  base: "/",

  server: {
    host: "0.0.0.0",
    port: 5173,
    open: true,
    proxy: {
      // Dev: forward API calls to the FastAPI backend (uvicorn default here).
      "/api": {
        target: "http://localhost:8077",
        changeOrigin: true,
      },
    },
  },

  build: {
    // Built assets land next to the FastAPI app so uvicorn can mount them.
    outDir: "../app/dist",
    emptyOutDir: true,
    sourcemap: false,
  },

  plugins: [react()],

  esbuild: { jsxDev: false, jsx: "automatic" },

  resolve: {
    alias: {
      "@store": path.resolve(__dirname, "./src/store"),
      "@components": path.resolve(__dirname, "./src/components"),
      "@utils": path.resolve(__dirname, "./src/utils"),
      "@api": path.resolve(__dirname, "./src/utils/api"),
    },
  },
});
