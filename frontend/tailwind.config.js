/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172230",
        muted: "#6d7888",
        line: "#e7ebf1",
        canvas: "#f5f7fb",
        brand: "#266b58",
        "brand-dark": "#194b3d",
        "brand-soft": "#e9f4ef",
        gold: "#d99b3d",
      },
      boxShadow: {
        card: "0 8px 26px rgba(27, 44, 63, 0.045)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
