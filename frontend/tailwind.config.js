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
        hindi: ["'Noto Sans Devanagari'", 'sans-serif'],
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)'
      },
      colors: {
        // HOME GENIES glass palette
        hg: {
          bg: '#10091D',
          bg2: '#190E2B',
          deep: '#29104D',
          violet: '#8B3DFF',
          lavender: '#C69BFF',
          pink: '#ED9BEA',
          text2: '#C9BED9',
          muted: '#9185A4',
          success: '#55D6A5',
          gold: '#F2CB4B',
        },
        forest: '#2E1065',
        brand: {
          DEFAULT: '#6D28D9',
          50: '#F5F0FF',
          100: '#EDE4FF',
          600: '#6D28D9',
          700: '#2E1065',
        },
        gold: {
          DEFAULT: '#C9A227',
          light: '#FBF3DA',
        },
        magenta: {
          DEFAULT: '#C026A3',
          light: '#FBE8F6',
        },
        ink: '#1B1024',
        muted2: '#6B6475',
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
