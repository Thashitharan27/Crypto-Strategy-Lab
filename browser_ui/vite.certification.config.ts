/** Explicit standalone certification build; never included in production dist. */
import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  root: "certification",
  server: {host: "127.0.0.1"},
  build: {outDir: "../dist-certification", emptyOutDir: true},
});
