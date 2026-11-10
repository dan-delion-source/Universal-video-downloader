import { defineConfig } from 'vite';
export default defineConfig({
  esbuild: { jsx: 'automatic', jsxImportSource: 'preact' },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { target: 'es2020', outDir: 'dist' },
});
