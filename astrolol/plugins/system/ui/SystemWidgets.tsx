// Host health for the dock. The host publishes no events, so this reads it every 10 s while shown.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ProgressBar } from '@/components/ui/progress-bar'
import { StatusPill } from '@/components/ui/badge'
import type { SystemStatus, ThrottleStatus } from '@/api/types'
import * as api from './api'

const POLL_MS = 10_000

function Meter({ label, percent, detail }: { label: string; percent: number; detail?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between font-mono text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="text-slate-300">{percent.toFixed(0)}%{detail ? ` · ${detail}` : ''}</span>
      </div>
      <ProgressBar value={percent} max={100} label={label} />
    </div>
  )
}

export function SystemHealthWidget() {
  const { t } = useTranslation('system')
  const [sys, setSys] = useState<SystemStatus | null>(null)
  const [power, setPower] = useState<ThrottleStatus | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => {
      api.getSystemStatus().then((s) => { if (alive) setSys(s) }).catch(() => {})
      api.getThrottleStatus().then((s) => { if (alive) setPower(s) }).catch(() => {})
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  if (!sys) return null
  const hot = sys.temperature_celsius != null && sys.temperature_celsius >= 70
  return (
    <div className="flex flex-col gap-2">
      {power?.available && (power.underpowered || power.throttled) && (
        <StatusPill variant="red" pulse status={power.underpowered ? t('chip.underpowered') : t('widget.throttled')} />
      )}
      <Meter label={t('widget.cpu')} percent={sys.cpu_percent} />
      <Meter label={t('widget.memory')} percent={sys.memory_percent} />
      <Meter label={t('widget.disk')} percent={sys.disk_percent} detail={t('widget.free', { gb: (sys.disk_total_gb - sys.disk_used_gb).toFixed(0) })} />
      {sys.temperature_celsius != null && (
        <div className="flex justify-between font-mono text-xs">
          <span className="text-slate-500">{t('widget.temperature')}</span>
          <span className={hot ? 'text-status-error' : 'text-slate-300'}>{sys.temperature_celsius.toFixed(0)}°C{hot ? ` · ${t('widget.hot')}` : ''}</span>
        </div>
      )}
    </div>
  )
}
