import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:3000",
      "/montage": "http://127.0.0.1:8000",
      "/youtube": "http://127.0.0.1:8000"
    }
  }
});
