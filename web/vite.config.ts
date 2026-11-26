import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

// Chạy thử ngoài Docker: `npm run dev` mở http://localhost:8080 (đúng địa chỉ đã khai báo với Google),
// /api được chuyển tới FastAPI ở cổng 8000 và bỏ tiền tố /api — giống nginx khi chạy trong Docker.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 8080,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 800 },
});
