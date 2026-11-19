import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser calls /api/... on the Vite dev server, which forwards it to the FastAPI service.
// Same origin for the browser, so no CORS setting is needed in the API's .env.
// Change the target if the API runs somewhere else (VITE_API_TARGET=http://host:port).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
