/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: ["class"],
    content: [
    "./src/**/*.{js,jsx,ts,tsx}",
    "./public/index.html"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Poppins', 'Inter', 'sans-serif'],
        serif: ['"Playfair Display"', 'Georgia', 'serif'],
        hindi: ["'Noto Sans Devanagari'", 'sans-serif'],
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)'
      },
      colors: {
        // HOME GENIES glass palette
        // HOME GENIES design system: warm cream + deep chocolate + rich gold (class names kept from the old palette)
        hg: {
          bg: '#FBF6EC',
          bg2: '#F4EAD7',
          deep: '#3B2417',
          violet: '#6B4127',
          lavender: '#A9842A',
          pink: '#B8653A',
          text2: '#6B5642',
          muted: '#8A7660',
          success: '#2F8A57',
          gold: '#C9A13B',
        },
        forest: '#3B2417',
        brand: {
          DEFAULT: '#5C3A26',
          50: '#FBF1DA',
          100: '#F4E6C6',
          600: '#5C3A26',
          700: '#3B2417',
        },
        gold: {
          DEFAULT: '#C9A227',
          light: '#FBF3DA',
        },
        magenta: {
          DEFAULT: '#B8653A',
          light: '#FBEADF',
        },
        // Vendor Pillar design system (cream / chocolate / gold). Scoped: used only by vendor + admin-vendor screens.
        cream: { 50: '#FFFDF8', 100: '#FBF6EC', 200: '#F4EAD7', 300: '#E9D9BC', 400: '#D9C29A' },
        choco: { 500: '#7A5038', 600: '#5C3A26', 700: '#4A2E1E', 800: '#3B2417', 900: '#2B1A10' },
        aurum: { 200: '#F3E3B5', 300: '#EAD394', 400: '#DDB862', 500: '#C9A13B', 600: '#A9842A', 700: '#86671E' },
        ink: '#2B1A10',
        muted2: '#7A6450',
        danger: '#C62828',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))'
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))'
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))'
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))'
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))'
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))'
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))'
        },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        chart: {
          '1': 'hsl(var(--chart-1))',
          '2': 'hsl(var(--chart-2))',
          '3': 'hsl(var(--chart-3))',
          '4': 'hsl(var(--chart-4))',
          '5': 'hsl(var(--chart-5))'
        }
      },
      boxShadow: {
        soft: '0 4px 24px rgba(11,77,46,0.06)',
        card: '0 2px 12px rgba(11,77,46,0.05)',
        lift: '0 12px 32px rgba(11,77,46,0.12)',
      },
      keyframes: {
        'accordion-down': { from: { height: '0' }, to: { height: 'var(--radix-accordion-content-height)' } },
        'accordion-up': { from: { height: 'var(--radix-accordion-content-height)' }, to: { height: '0' } },
        'fade-up': { '0%': { opacity: '0', transform: 'translateY(12px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'fade-up': 'fade-up 0.5s cubic-bezier(0.16,1,0.3,1)',
      }
    }
  },
  plugins: [require("tailwindcss-animate")],
};
