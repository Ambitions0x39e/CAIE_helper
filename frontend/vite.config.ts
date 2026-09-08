import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // pywebview loads dist/index.html off the filesystem, where the default
  // absolute "/assets/…" resolves against the drive root and 404s. Relative
  // paths are what make the built page work under file://.
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    // The bundle is read off the local disk by pywebview, not fetched over a
    // network, so the 500 kB default — a download-time heuristic for web
    // pages — has nothing to warn about here.
    chunkSizeWarningLimit: 1000,
  },
})
