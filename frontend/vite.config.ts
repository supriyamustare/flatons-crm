import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In local dev, forward /api to the FastAPI server so cookies stay same-origin.
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
