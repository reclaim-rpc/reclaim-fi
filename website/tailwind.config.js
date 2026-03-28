/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts}'],
  theme: {
    extend: {
      colors: {
        dark: {
          DEFAULT: '#0a0b0f',
          card: '#1a1b23',
          surface: '#14151a',
        },
        accent: {
          DEFAULT: '#00ff88',
          dim: '#00cc6a',
        },
        teal: {
          DEFAULT: '#0ea5e9',
        },
        danger: {
          DEFAULT: '#ef4444',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
};
