/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#eef4ff",
          100: "#dae6ff",
          500: "#3b6bff",
          600: "#2a52e0",
          700: "#1f3fb3",
        },
      },
    },
  },
  plugins: [],
};
