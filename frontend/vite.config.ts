import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    // The Python package serves the built files from its static/ folder.
    outDir: "../midwire_web_ui/static",
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` talks to a backend started separately (see README).
    proxy: { "/api": process.env.MIDWIRE_BACKEND ?? "http://127.0.0.1:8080" },
  },
});
