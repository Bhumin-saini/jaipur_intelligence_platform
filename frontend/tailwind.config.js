/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        jip: {
          dark:   '#0f172a',
          panel:  '#1e293b',
          border: '#334155',
          accent: '#f97316',
        },
      },
    },
  },
  plugins: [],
}
