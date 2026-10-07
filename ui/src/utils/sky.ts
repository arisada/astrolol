// Sky geometry for the mount position widgets. Pure functions, tested against astropy.
//
// Conventions: latitude and declination in degrees (north +), LST and RA in hours, hour angle in
// degrees (west +), altitude and azimuth in degrees (azimuth from north through east).

const D2R = Math.PI / 180

/** Hour angle in degrees, in (−180, 180]. */
export function hourAngle(lstHours: number, raHours: number): number {
  const h = (((lstHours - raHours) * 15) % 360 + 360) % 360
  return h > 180 ? h - 360 : h
}

export interface AltAz { alt: number; az: number }

/** Horizontal coordinates of a point given its hour angle and declination, for an observer at `lat`. */
export function equatorialToHorizontal(lat: number, haDeg: number, decDeg: number): AltAz {
  const phi = lat * D2R, delta = decDeg * D2R, h = haDeg * D2R
  const alt = Math.asin(Math.sin(phi) * Math.sin(delta) + Math.cos(phi) * Math.cos(delta) * Math.cos(h))
  const y = Math.sin(delta) * Math.cos(phi) - Math.cos(delta) * Math.cos(h) * Math.sin(phi)
  const x = -Math.cos(delta) * Math.sin(h)
  return { alt: alt / D2R, az: ((Math.atan2(x, y) / D2R) + 360) % 360 }
}

/**
 * The horizon (altitude 0) as hour angle / declination pairs, one per `stepDeg` of azimuth. It
 * is a closed curve around the visible celestial pole for any |latitude| < 90°.
 */
export function horizonCurve(lat: number, stepDeg = 4): { ha: number; dec: number }[] {
  const phi = lat * D2R
  const out: { ha: number; dec: number }[] = []
  for (let az = 0; az <= 360; az += stepDeg) {
    const a = az * D2R
    const dec = Math.asin(Math.cos(phi) * Math.cos(a)) / D2R
    const ha = Math.atan2(-Math.sin(a), -Math.sin(phi) * Math.cos(a)) / D2R
    out.push({ ha, dec })
  }
  return out
}

/** Round-number tick positions between lo and hi: about `target` major ticks and 5 minors per major. */
export function niceTicks(lo: number, hi: number, target = 5): { major: number[]; minor: number[]; step: number } {
  const span = Math.max(hi - lo, 1e-9)
  const raw = span / target
  const pow = 10 ** Math.floor(Math.log10(raw))
  const f = raw / pow
  const step = (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * pow
  const minorStep = step / 5
  const list = (s: number) => {
    const first = Math.ceil(lo / s - 1e-9)
    const last = Math.floor(hi / s + 1e-9)
    return Array.from({ length: Math.max(0, last - first + 1) }, (_, i) => +((first + i) * s).toFixed(10))
  }
  const major = list(step)
  const minor = list(minorStep).filter((v) => !major.includes(v))
  return { major, minor, step }
}
