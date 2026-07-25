/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        'bg-alt': 'var(--color-bg-alt)',
        text: 'var(--color-text)',
        'text-muted': 'var(--color-text-muted)',
        border: 'var(--color-border)',
        'card-bg': 'var(--color-card-bg)',
        accent: 'var(--color-accent)',
        'accent-hover': 'var(--color-accent-hover)',
        'accent-text': 'var(--color-accent-text)',
        success: 'var(--color-success)',
        error: 'var(--color-error)',
        warning: 'var(--color-warning)',
      },
      spacing: {
        '1': 'var(--space-1)',
        '2': 'var(--space-2)',
        '3': 'var(--space-3)',
        '4': 'var(--space-4)',
        '5': 'var(--space-5)',
        '6': 'var(--space-6)',
      },
      fontFamily: {
        heading: ['var(--font-heading)', 'sans-serif'],
        body: ['var(--font-body)', 'sans-serif'],
      },
      fontWeight: {
        regular: 'var(--weight-regular)',
        medium: 'var(--weight-medium)',
        bold: 'var(--weight-bold)',
        extrabold: 'var(--weight-extrabold)',
      },
      fontSize: {
        body: 'var(--text-body)',
        'body-mobile': 'var(--text-body-mobile)',
        small: 'var(--text-small)',
        h3: 'var(--text-h3)',
        h2: 'var(--text-h2)',
        h1: 'var(--text-h1)',
      },
      lineHeight: {
        body: 'var(--line-height-body)',
        heading: 'var(--line-height-heading)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        hover: 'var(--shadow-hover)',
      },
      transitionDuration: {
        hover: 'var(--duration-hover)',
        dropdown: 'var(--duration-dropdown)',
        modal: 'var(--duration-modal)',
        max: 'var(--duration-max)',
      },
    },
  },
  plugins: [],
}
