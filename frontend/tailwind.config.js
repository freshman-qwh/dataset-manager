/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      boxShadow: {
        soft: "0 18px 45px rgba(15, 23, 42, 0.08)"
      },
      colors: {
        ink: "#1f2937",
        line: "#e5e7eb",
        canvas: "#f7f7f5"
      }
    }
  },
  plugins: []
};
