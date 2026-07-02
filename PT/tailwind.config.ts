import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        sentinel: {
          black: '#0a0a0f',
          surface: '#0d1117',
          green: '#00ff41',
          cyan: '#00b4d8',
          red: '#ff003c',
          amber: '#ff9f1c',
          text: '#e0ffe0',
          muted: '#8892a4',
          border: '#1a2a1a',
        },
      },
      fontFamily: {
        display: ['Orbitron', 'monospace'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        'glow-green': '0 0 8px #00ff41, 0 0 20px #00ff4133',
        'glow-red': '0 0 8px #ff003c, 0 0 20px #ff003c33',
        'glow-cyan': '0 0 8px #00b4d8, 0 0 20px #00b4d833',
        'glow-amber': '0 0 8px #ff9f1c, 0 0 20px #ff9f1c33',
      },
      animation: {
        'tracking-pulse': 'trackingPulse 1.5s ease-in-out infinite',
        'slide-in': 'slideIn 0.3s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
        'glow-pulse': 'glowPulse 2s ease-in-out infinite',
        'scanline': 'scanline 6s linear infinite',
        'flicker': 'flicker 3s infinite',
        'matrix-fade': 'matrixFade 1.5s ease-out',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        trackingPulse: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(255, 0, 60, 0.7)' },
          '50%': { boxShadow: '0 0 0 8px rgba(255, 0, 60, 0)' },
        },
        slideIn: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 5px #00ff41, 0 0 10px #00ff4122' },
          '50%': { boxShadow: '0 0 15px #00ff41, 0 0 30px #00ff4144' },
        },
        scanline: {
          '0%': { transform: 'translateY(-100%)', opacity: '0.3' },
          '50%': { opacity: '0.15' },
          '100%': { transform: 'translateY(100vh)', opacity: '0' },
        },
        flicker: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.85' },
          '52%': { opacity: '1' },
          '54%': { opacity: '0.9' },
        },
        matrixFade: {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
