import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, the client talks to same-origin /api and /sync and Vite forwards them
// to the backend - exactly the shape production has behind Caddy, so there is
// no CORS and no environment-specific URL logic in the app.
export default defineConfig({
  plugins: [react()],
  envDir: '../../', // read the repo-root .env (only VITE_* vars reach the browser)
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/sync': { target: 'ws://localhost:8001', ws: true },
    },
  },
  build: { target: 'es2020', sourcemap: false },
})
