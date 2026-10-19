import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { FlatPanelStatus } from '@/api/types'
import { Button } from '@/components/ui/button'
import { LabeledSlider } from '@/components/ui/labeled-slider'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type { DockWidgetProps } from '../registry'
import { useDevice } from './useDevice'

const POLL_MS = 3000

/** Dust cover and light of a flat panel. Reads the panel while it is on screen (a cover takes a while to move). */
export function FlatPanelWidget({ deviceId }: DockWidgetProps) {
  const { t } = useTranslation('imaging')
  const { t: tc } = useTranslation()
  const id = useDevice('flat_panel', deviceId)
  const [status, setStatus] = useState<FlatPanelStatus | null>(null)
  const [level, setLevel] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!id) return
    try {
      setStatus(await api.flatPanel.status(id))
    } catch { /* the panel is read again on the next tick */ }
  }, [id])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(timer)
  }, [refresh])

  const act = async (call: (id: string) => Promise<FlatPanelStatus>) => {
    if (!id) return
    setError(null)
    try {
      setStatus(await call(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (!id) return <p className="text-xs text-slate-500">{tc('dock.noFlatPanel')}</p>
  if (!status) return null

  const max = status.max_brightness ?? 255
  const brightness = level ?? status.brightness ?? 0
  const moving = status.cover === 'moving'

  return (
    <div className="flex flex-col gap-3">
      {status.has_cover && (
        <div className="flex items-center gap-2">
          <span className="label-caps text-slate-400 flex-1">
            {t('flatPanel.cover')}: <span className="font-mono text-slate-200">{t(`flatPanel.state.${status.cover ?? 'unknown'}`)}</span>
          </span>
          <Button size="sm" variant="outline" disabled={moving || status.cover === 'open'}
            onClick={() => void act((i) => api.flatPanel.openCover(i))}>
            {t('flatPanel.openCover')}
          </Button>
          <Button size="sm" variant="outline" disabled={moving || status.cover === 'closed'}
            onClick={() => void act((i) => api.flatPanel.closeCover(i))}>
            {t('flatPanel.closeCover')}
          </Button>
        </div>
      )}
      {status.has_light && (
        <>
          <div className="flex items-center justify-between">
            <span className="label-caps text-slate-400">{t('flatPanel.light')}</span>
            <ToggleSwitch
              checked={status.light_on === true}
              label={t('flatPanel.light')}
              onChange={() => void act((i) => api.flatPanel.setLight(i, status.light_on !== true, brightness))}
            />
          </div>
          <LabeledSlider
            label={t('flatPanel.brightness')}
            value={brightness} min={0} max={max} step={1}
            format={(v) => `${v} / ${max}`}
            onChange={setLevel}
            onCommit={(v) => { setLevel(null); void act((i) => api.flatPanel.setLight(i, status.light_on === true, v)) }}
          />
        </>
      )}
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  )
}
