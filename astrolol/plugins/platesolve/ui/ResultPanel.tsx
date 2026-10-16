import { useTranslation } from 'react-i18next'
import { fmtRA, fmtDec } from '@/utils/formatting'
import type { SolveJob } from './api'

function fmtField(deg: number): string {
  return deg >= 1 ? `${deg.toFixed(2)}°` : `${(deg * 60).toFixed(1)}′`
}

// ── Offset helpers ─────────────────────────────────────────────────────────────

function angularSepArcsec(ra1: number, dec1: number, ra2: number, dec2: number): number {
  const R = Math.PI / 180
  const d1 = dec1 * R, d2 = dec2 * R, dra = (ra2 - ra1) * R, ddec = (dec2 - dec1) * R
  const a = Math.sin(ddec / 2) ** 2 + Math.cos(d1) * Math.cos(d2) * Math.sin(dra / 2) ** 2
  return 2 * Math.asin(Math.min(1, Math.sqrt(a))) * (180 / Math.PI) * 3600
}

function fmtOffset(arcsec: number): string {
  const sign = arcsec >= 0 ? '+' : '−'
  const abs = Math.abs(arcsec)
  if (abs >= 3600) return `${sign}${(abs / 3600).toFixed(2)}°`
  if (abs >= 60)   return `${sign}${(abs / 60).toFixed(1)}′`
  return `${sign}${abs.toFixed(1)}″`
}

function fmtSep(arcsec: number): string {
  if (arcsec >= 3600) return `${(arcsec / 3600).toFixed(2)}°`
  if (arcsec >= 60)   return `${(arcsec / 60).toFixed(1)}′`
  return `${arcsec.toFixed(1)}″`
}

// ── Result panel ───────────────────────────────────────────────────────────────

export function ResultPanel({ job, className = 'mx-4 mb-3' }: { job: SolveJob; className?: string }) {
  const { t } = useTranslation('platesolve')
  const result = job.result!
  const raHint = job.request.ra_hint
  const decHint = job.request.dec_hint
  const hasHint = raHint != null && decHint != null

  const deltaRaArcsec  = hasHint ? (result.ra - raHint) * Math.cos(result.dec * Math.PI / 180) * 3600 : null
  const deltaDecArcsec = hasHint ? (result.dec - decHint) * 3600 : null
  const totalArcsec    = hasHint ? angularSepArcsec(raHint, decHint, result.ra, result.dec) : null

  return (
    <div className={`${className} rounded-lg border border-green-500/30 bg-green-500/5 p-3`}>
      <div className="font-medium text-green-400 label-caps mb-2">{t('result.solved')}</div>
      <div className="grid grid-cols-1 gap-y-1 text-xs">
        <div><span className="text-slate-500">{t('result.ra')}</span>
          <span className="ml-2 font-mono text-slate-200">{fmtRA(result.ra / 15)}</span></div>
        <div><span className="text-slate-500">{t('result.dec')}</span>
          <span className="ml-2 font-mono text-slate-200">{fmtDec(result.dec)}</span></div>
        <div><span className="text-slate-500">{t('result.rotation')}</span>
          <span className="ml-2 font-mono text-slate-200">{result.rotation.toFixed(2)}°</span></div>
        <div><span className="text-slate-500">{t('result.scale')}</span>
          <span className="ml-2 font-mono text-slate-200">{result.pixel_scale.toFixed(3)}″/px</span></div>
        <div><span className="text-slate-500">{t('result.field')}</span>
          <span className="ml-2 font-mono text-slate-200">{fmtField(result.field_w)} × {fmtField(result.field_h)}</span></div>
        <div><span className="text-slate-500">{t('result.time')}</span>
          <span className="ml-2 font-mono text-slate-200">{(result.duration_ms / 1000).toFixed(1)}s</span></div>
      </div>
      {totalArcsec != null && deltaRaArcsec != null && deltaDecArcsec != null && (
        <>
          <div className="mt-2 mb-1 border-t border-green-500/20" />
          <div className="font-medium text-slate-500 label-caps mb-1">{t('result.offset')}</div>
          <div className="grid grid-cols-1 gap-y-1 text-xs">
            <div><span className="text-slate-500">{t('result.dRa')}</span>
              <span className="ml-2 font-mono text-slate-300">{fmtOffset(deltaRaArcsec)}</span></div>
            <div><span className="text-slate-500">{t('result.dDec')}</span>
              <span className="ml-2 font-mono text-slate-300">{fmtOffset(deltaDecArcsec)}</span></div>
            <div><span className="text-slate-500">{t('result.total')}</span>
              <span className="ml-2 font-mono text-amber-400 font-medium">{fmtSep(totalArcsec)}</span></div>
          </div>
        </>
      )}
    </div>
  )
}
