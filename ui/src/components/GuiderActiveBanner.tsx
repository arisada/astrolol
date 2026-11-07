import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { isInactiveGuider, refreshActiveGuider, useActiveGuider } from '@/hooks/useActiveGuider'
import { useStore } from '@/store'

/** At the top of a guiding plugin's page: says so when another guider is the one in use. */
export function GuiderActiveBanner({ pluginId }: { pluginId: string }) {
  const { t } = useTranslation()
  const guider = useActiveGuider()
  const names = useStore((s) => s.pluginInfos)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!guider || !isInactiveGuider(guider, pluginId)) return null

  const name = (id: string | null) => names.find((p) => p.id === id)?.name ?? id ?? ''
  const use = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.guiding.choose(pluginId)
      await refreshActiveGuider()
    } catch (e) {
      setError(e instanceof Error ? e.message : t('guiderActive.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2">
      <p className="text-xs text-amber-300">
        {t('guiderActive.inactive', { active: name(guider.active), name: name(pluginId) })}
      </p>
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={use} disabled={busy}>{t('guiderActive.use', { name: name(pluginId) })}</Button>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </div>
  )
}
