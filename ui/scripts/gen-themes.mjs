// Generates src/themes.css: the palettes selectable in Options -> Palette.
//
//   node scripts/gen-themes.mjs     (or: npm run gen:themes)
//
// Tailwind's stock colour names (slate, sky, emerald, ...) are redirected to CSS variables in
// tailwind.config.js, so every class in the app is themed without being renamed. The "current"
// palette reproduces Tailwind's own values exactly; the others are described by a handful of base
// colours below and the 100-900 shades are derived from them.
import { writeFileSync } from 'node:fs'
import colors from 'tailwindcss/colors.js'

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const mix = (a, b, t) => hex(a).map((v, i) => Math.round(v + (hex(b)[i] - v) * t))
const scale = (a, k) => hex(a).map((v) => Math.min(255, Math.round(v * k)))
const trip = (c) => (typeof c === 'string' ? hex(c) : c).join(' ')

// bg / bg1 / bg2 / line: page, raised, overlay, border.  tx / tx2 / tx3: text, muted, faint.
// ok / busy / err / idle: status.  s1 / s2: the two chart series (always distinguishable).
export const PALETTES = {
  midnight: { label: 'Midnight', accentDim: '#3a6bc2', bg: '#0f1117', bg1: '#1a1d27', bg2: '#242838', line: '#2e3347', tx: '#e2e8f0', tx2: '#94a3b8', tx3: '#64748b', accent: '#4f8ef7', onAccent: '#ffffff', ok: '#4ade80', busy: '#facc15', err: '#f87171', idle: '#94a3b8', s1: '#60a5fa', s2: '#f87171' },
  atlas: { label: 'Atlas', bg: '#070b14', bg1: '#0b1220', bg2: '#121c31', line: '#1f2e4d', tx: '#cdd9f0', tx2: '#7f93b8', tx3: '#4a5c82', accent: '#f2c14e', onAccent: '#1a1204', ok: '#6fd0a0', busy: '#f2c14e', err: '#ec6b72', idle: '#6f82a8', s1: '#8ab4ff', s2: '#f2c14e' },
  graphite: { label: 'Graphite', bg: '#0e0e0d', bg1: '#171716', bg2: '#222220', line: '#2f2f2c', tx: '#dcd9d2', tx2: '#98958c', tx3: '#66645d', accent: '#e5a54b', onAccent: '#1a1204', ok: '#8cc084', busy: '#e5a54b', err: '#e0675a', idle: '#8a877e', s1: '#e5a54b', s2: '#9ab0c4' },
  void: { label: 'Void', bg: '#000000', bg1: '#0b0c0d', bg2: '#16181a', line: '#25282b', tx: '#e6e8ea', tx2: '#8d9399', tx3: '#5a6066', accent: '#4fd1c5', onAccent: '#00110f', ok: '#5fd79a', busy: '#f2c14e', err: '#f06a6a', idle: '#7b8288', s1: '#4fd1c5', s2: '#f2c14e' },
  nebula: { label: 'Nebula', bg: '#0c0911', bg1: '#150f1c', bg2: '#201828', line: '#2e2338', tx: '#e3dcec', tx2: '#9a8bad', tx3: '#645673', accent: '#f0709a', onAccent: '#1f0610', ok: '#79d4a8', busy: '#f2c14e', err: '#ff5a4d', idle: '#8a7c9b', s1: '#f0709a', s2: '#79d4a8' },
  mono: { label: 'Mono', bg: '#0b0b0c', bg1: '#141415', bg2: '#1e1e20', line: '#2c2c2f', tx: '#e8e8e6', tx2: '#9a9a98', tx3: '#66666a', accent: '#f2f2ee', onAccent: '#0b0b0c', ok: '#9fd6a4', busy: '#e2c27a', err: '#e57373', idle: '#8a8a8c', s1: '#f2f2ee', s2: '#8a8a8c' },
  ember: { label: 'Ember', bg: '#100b08', bg1: '#1a130e', bg2: '#261c15', line: '#38291f', tx: '#e8d5c0', tx2: '#a58f79', tx3: '#6f5d4c', accent: '#e2833b', onAccent: '#1c0d03', ok: '#9bc47a', busy: '#f0b44a', err: '#e5604f', idle: '#9a8570', s1: '#e2833b', s2: '#9bc47a' },
  night: { label: 'Night red', bg: '#0a0605', bg1: '#140c0a', bg2: '#1f1311', line: '#34201b', tx: '#e0866e', tx2: '#a35d4a', tx3: '#6b3d31', accent: '#ff5b3a', onAccent: '#1a0603', ok: '#d99a4a', busy: '#ff8a3d', err: '#ff3b30', idle: '#8a5143', s1: '#ff5b3a', s2: '#a35d4a', red: true },
  crimson: { label: 'Night crimson', bg: '#070203', bg1: '#0f0506', bg2: '#190809', line: '#2b0f11', tx: '#cf4a44', tx2: '#8f2f2c', tx3: '#5c1f1e', accent: '#ff3b30', onAccent: '#1a0302', ok: '#b8503f', busy: '#ff6a3d', err: '#ff2d2d', idle: '#7a2d28', s1: '#ff3b30', s2: '#7a2d28', red: true },
}

// Tailwind colour name -> role that supplies its base (the 400 shade) in derived palettes.
const ROLE = { emerald: 'ok', green: 'ok', amber: 'busy', yellow: 'busy', orange: 'busy', rose: 'err', red: 'err', sky: 'info', blue: 'info', cyan: 'info', teal: 'info', violet: 'compute', purple: 'compute', indigo: 'accent' }
const SHADES = [100, 200, 300, 400, 500, 600, 700, 800, 900]
const CAT_CURRENT = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#64748b']

function derived(p) {
  const base = { ok: p.ok, busy: p.busy, err: p.err, info: p.s1, compute: mix(p.s1, p.s2, 0.5), accent: p.accent }
  const out = {}
  const toward = { 100: [p.tx, 0.8], 200: [p.tx, 0.55], 300: [p.tx, 0.28], 500: [p.bg, 0.25], 600: [p.bg, 0.45], 700: [p.bg, 0.62], 800: [p.bg, 0.78], 900: [p.bg, 0.88] }
  for (const [name, role] of Object.entries(ROLE)) {
    const b = typeof base[role] === 'string' ? base[role] : '#' + base[role].map((v) => v.toString(16).padStart(2, '0')).join('')
    out[name] = {}
    for (const s of SHADES) out[name][s] = s === 400 ? hex(b) : mix(b, ...toward[s])
  }
  const slate = { 100: scale(p.tx, 1.12), 200: hex(p.tx), 300: mix(p.tx, p.tx2, 0.5), 400: hex(p.tx2), 500: hex(p.tx3), 600: mix(p.tx3, p.line, 0.45), 700: hex(p.line), 800: hex(p.bg2), 900: mix(p.bg, p.bg1, 0.5) }
  return { ...out, slate }
}

function block(sel, id, p) {
  const L = [`${sel} {`]
  const sh = id === 'midnight' ? Object.fromEntries([...Object.keys(ROLE), 'slate'].map((n) => [n, Object.fromEntries(SHADES.map((s) => [s, colors[n][s]]))])) : derived(p)
  for (const [n, ramp] of Object.entries(sh))
    for (const s of SHADES) L.push(`  --c-${n}-${s}: ${trip(typeof ramp[s] === 'string' ? hex(ramp[s]) : ramp[s])};`)
  const o = { surface: p.bg, 'surface-raised': p.bg1, 'surface-overlay': p.bg2, 'surface-border': p.line, accent: p.accent, 'accent-dim': p.accentDim ?? mix(p.accent, p.bg, 0.3), 'accent-fg': p.onAccent, 'status-connected': p.ok, 'status-error': p.err, 'status-busy': p.busy, 'status-idle': p.idle, 'series-1': p.s1, 'series-2': p.s2 }
  for (const [k, v] of Object.entries(o)) L.push(`  --c-${k}: ${trip(v)};`)
  const cat = id === 'midnight' || !p.red ? CAT_CURRENT : [0, 0.2, 0.38, 0.52, 0.64, 0.76].map((t) => '#' + mix(p.accent, p.bg, t).map((v) => v.toString(16).padStart(2, '0')).join(''))
  cat.forEach((c, i) => L.push(`  --c-cat-${i + 1}: ${trip(c)};`))
  L.push(`  color-scheme: dark;`, '}')
  return L.join('\n')
}

const ids = Object.keys(PALETTES)
const css = ['/* GENERATED by scripts/gen-themes.mjs - edit the script, not this file. */',
  block(':root', 'midnight', PALETTES.midnight),
  ...ids.filter((i) => i !== 'midnight').map((i) => block(`[data-theme='${i}']`, i, PALETTES[i]))].join('\n\n') + '\n'
writeFileSync(new URL('../src/themes.css', import.meta.url), css)
writeFileSync(new URL('../src/themes.ts', import.meta.url),
  `// GENERATED by scripts/gen-themes.mjs - edit the script, not this file.\nexport const THEMES = ${JSON.stringify(ids.map((id) => ({ id, label: PALETTES[id].label, bg1: PALETTES[id].bg1 })), null, 2)} as const\nexport type ThemeId = (typeof THEMES)[number]['id']\n`)
