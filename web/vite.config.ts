import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev na 5173 (bate com WEB_BASE_URL do backend, destino do magic-link).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
