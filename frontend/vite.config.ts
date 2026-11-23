import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@senascl/shared-types': path.resolve(__dirname, '../../packages/shared-types/src'),
      '@senascl/core-ml': path.resolve(__dirname, '../../packages/core-ml/src'),
      '@senascl/landmarks': path.resolve(__dirname, '../../packages/landmarks/src'),
      '@senascl/nlp-lsch': path.resolve(__dirname, '../../packages/nlp-lsch/src'),
      '@senascl/tts': path.resolve(__dirname, '../../packages/tts/src'),
      '@senascl/ui-kit': path.resolve(__dirname, '../../packages/ui-kit/src'),
    },
  },
  server: {
    port: 3000,
  },
});
