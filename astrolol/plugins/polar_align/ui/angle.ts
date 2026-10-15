/** Angle in arcminutes as `1° 05′`, `12′ 30″` or `45″`, whichever is shortest to read. */
export function fmtArcmin(arcmin: number): string {
  const totalArcsec = Math.round(Math.abs(arcmin) * 60)
  const deg = Math.floor(totalArcsec / 3600)
  const min = Math.floor((totalArcsec % 3600) / 60)
  const sec = totalArcsec % 60
  if (deg > 0) return `${deg}° ${String(min).padStart(2, '0')}′`
  if (min > 0) return sec === 0 ? `${min}′` : `${min}′ ${String(sec).padStart(2, '0')}″`
  return `${sec}″`
}

export type ArrowDirection = 'up' | 'down' | 'left' | 'right'

export interface KnobMove {
  vertical: { direction: 'up' | 'down'; arcmin: number }
  horizontal: { direction: 'left' | 'right'; arcmin: number }
}

/**
 * Which way the polar axis has to be moved, as seen from behind the mount facing the pole.
 * A positive altitude error is an axis that points too high (move it down); a positive
 * azimuth error is one that points east of the pole's azimuth, i.e. to be turned
 * counter-clockwise seen from above, which is leftwards facing the pole in either hemisphere.
 */
export function knobMove(altErrorArcmin: number, azErrorArcmin: number): KnobMove {
  return {
    vertical: { direction: altErrorArcmin >= 0 ? 'down' : 'up', arcmin: Math.abs(altErrorArcmin) },
    horizontal: { direction: azErrorArcmin >= 0 ? 'left' : 'right', arcmin: Math.abs(azErrorArcmin) },
  }
}
