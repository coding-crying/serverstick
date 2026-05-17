import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  build: {
    outDir: 'build',
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
});