/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Unicorn Commander Brand Colors
        primary: {
          50: '#faf5ff',
          100: '#f3e8ff',
          200: '#e9d5ff',
          300: '#d8b4fe',
          400: '#c084fc',
          500: '#a855f7',
          600: '#9333ea',
          700: '#7c3aed',
          800: '#6b21a8',
          900: '#581c87',
          950: '#3b0764',
        },
        unicorn: {
          purple: '#b66eff',
          blue: '#00d4ff',
          gold: '#ffab00',
          green: '#00e676',
          red: '#ff5252',
          rainbow: {
            red: '#ff00cc',
            blue: '#3333ff',
            cyan: '#00ccff',
            orange: '#ff6600',
            purple: '#cc00ff',
            green: '#00ff99',
            pink: '#ff0066',
          }
        },
        commander: {
          navy: '#1e3a8a',
          gold: '#d97706',
          silver: '#6b7280',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      }
    },
  },
  plugins: [],
}