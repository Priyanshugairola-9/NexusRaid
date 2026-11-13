import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the dashboard runs on port 5173 and forwards /api requests
// to the FastAPI backend on port 8000, so no URL is hard-coded in the app.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
