import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
      '/documents': 'http://localhost:8000',
      '/users': 'http://localhost:8000',
    },
  },
});
