// After the ASCOM Alpaca logo (an alpaca on a curved horizon under a small constellation),
// redrawn as a line icon in the style of the other navigation icons: not the logo artwork itself.
export function AlpacaIcon({ size = 24, className }: { size?: number | string; className?: string }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true"
    >
      <path d="M1.5 21.6Q12 18 22.5 21.6" />
      <path d="M5.6 20.3C3 18 2.4 13.5 4 11.3C5.6 9.2 8.6 10.4 10.8 11.2C11.6 9 12.2 6 12.8 3.6L13.6 5.4L15.4 6.6L13.8 7.4C13.8 10 14.2 13.6 15 15.4L15.6 19.8" />
      <path d="M7.2 20.2C6.7 18 6.6 16 6.9 14.3C8.6 15.3 11.2 15.4 13.1 14.6C13.4 16.6 13.9 18.4 14.2 19.9" />
      <path d="M19.2 2.4L17.9 5.9M19.2 2.4L20.6 6.4M17.9 5.9L21.8 4" strokeWidth={1} />
      <g fill="currentColor" stroke="none">
        <circle cx="19.2" cy="2.4" r="0.95" />
        <circle cx="21.8" cy="4" r="0.95" />
        <circle cx="17.9" cy="5.9" r="0.95" />
        <circle cx="20.6" cy="6.4" r="0.95" />
      </g>
    </svg>
  )
}
