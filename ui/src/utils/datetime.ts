// Dates and times as the user's language writes them, never in a form that can be misread:
// the month is a word (7 Nov 2026) and the clock is 24-hour. Plain "en" would give the US order
// (11/7/2026), so English uses the day-first British conventions.

const locale = (lng: string) => (lng === 'en' ? 'en-GB' : lng)

type Options = { seconds?: boolean; timeZone?: string }

export function formatDate(value: string | number | Date, lng: string, { timeZone }: Options = {}): string {
  return new Intl.DateTimeFormat(locale(lng), { day: 'numeric', month: 'short', year: 'numeric', timeZone })
    .format(new Date(value))
}

export function formatClock(value: string | number | Date, lng: string, { seconds, timeZone }: Options = {}): string {
  return new Intl.DateTimeFormat(locale(lng), {
    hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined, hourCycle: 'h23', timeZone,
  }).format(new Date(value))
}

export function formatDateTime(value: string | number | Date, lng: string, options: Options = {}): string {
  return `${formatDate(value, lng, options)}, ${formatClock(value, lng, options)}`
}
