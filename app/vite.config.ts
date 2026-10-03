import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// file:// から読むので相対パスでビルドする
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
});
