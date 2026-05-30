/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['"SF Pro Rounded"', '"Nunito"', 'system-ui', '-apple-system', 'sans-serif'],
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', '"JetBrains Mono"', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      colors: {
        primary: {
          DEFAULT: 'var(--color-primary)',
          pressed: 'var(--color-primary-pressed)',
          on: 'var(--color-on-primary)',
        },
        canvas: {
          DEFAULT: 'var(--color-canvas)',
          soft: 'var(--color-canvas-soft)',
        },
        surface: {
          dark: 'var(--color-surface-dark)',
        },
        ink: {
          DEFAULT: 'var(--color-ink)',
          deep: 'var(--color-ink-deep)',
        },
        charcoal: 'var(--color-charcoal)',
        body: 'var(--color-body)',
        mute: 'var(--color-mute)',
        hairline: {
          DEFAULT: 'var(--color-hairline)',
          strong: 'var(--color-hairline-strong)',
        },
        'on-dark': {
          DEFAULT: 'var(--color-on-dark)',
          mute: 'var(--color-on-dark-mute)',
        },
        terminal: {
          red: 'var(--color-terminal-red)',
          yellow: 'var(--color-terminal-yellow)',
          green: 'var(--color-terminal-green)',
        },
      },
      borderRadius: {
        sm: '6px',
        md: '8px',
        lg: '12px',
        full: '9999px',
      },
      spacing: {
        'xxs': '2px',
        'xs': '4px',
        'section': '88px',
      },
      fontSize: {
        'display-xl': ['36px', { lineHeight: '1.11', fontWeight: '500' }],
        'display-lg': ['30px', { lineHeight: '1.2', fontWeight: '500' }],
        'heading-lg': ['24px', { lineHeight: '1.33', fontWeight: '600' }],
        'heading-md': ['20px', { lineHeight: '1.4', fontWeight: '500' }],
        'heading-sm': ['18px', { lineHeight: '1.56', fontWeight: '500' }],
      },
      animation: {
        'status-pulse': 'status-pulse 2s ease-in-out infinite',
        'shimmer': 'shimmer 1.5s ease-in-out infinite',
        'toast-in': 'toast-in 0.3s ease',
        'toast-out': 'toast-out 0.3s ease 3.5s forwards',
        'msg-enter': 'msg-enter 0.3s ease',
        'fade-in': 'fade-in 0.3s ease',
      },
      keyframes: {
        'status-pulse': {
          '0%, 100%': { boxShadow: '0 0 4px #22c55e' },
          '50%': { boxShadow: '0 0 12px #22c55e, 0 0 20px rgba(34,197,94,0.3)' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'toast-in': {
          from: { opacity: '0', transform: 'translateX(20px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        'toast-out': {
          from: { opacity: '1' },
          to: { opacity: '0', transform: 'translateX(20px)' },
        },
        'msg-enter': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
