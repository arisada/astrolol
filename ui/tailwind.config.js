/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}', '../plugins/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark astronomy palette
        surface: {
          DEFAULT: '#0f1117',
          raised: '#1a1d27',
          overlay: '#242838',
          border: '#2e3347',
        },
        accent: {
          DEFAULT: '#4f8ef7',
          dim: '#3a6bc2',
        },
        status: {
          connected: '#4ade80',
          error: '#f87171',
          busy: '#facc15',
          idle: '#94a3b8',
        },
      },
    },
  },
  plugins: [],
}
