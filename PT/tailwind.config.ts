import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        sentinel: {
          bg: '#0a0e1a',
          'bg-secondary': '#0f1629',
          card: '#141d35',
          border: '#1e2d4a',
          cyan: '#00d4ff',
          danger: '#ff3b3b',
          warning: '#ffaa00',
          success: '#00cc88',
          text: '#e8eaf2',
          muted: '#7a8db0',
          tracking: '#ff0040',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      animation: {
        'tracking-pulse': 'trackingPulse 1.5s ease-in-out infinite',
        'slide-in': 'slideIn 0.3s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
      },
      keyframes: {
        trackingPulse: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(255, 0, 64, 0.7)' },
          '50%': { boxShadow: '0 0 0 8px rgba(255, 0, 64, 0)' },
        },
        slideIn: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
