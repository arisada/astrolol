import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TriangleAlert } from 'lucide-react'
import { isInsecureTransport, useAuth } from '@/auth'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import * as api from './api'
import type { Level, SecuritySettings, TokenCreated, TokenOut, UserOut } from './api'
import { Page } from '@/components/Page'

const LEVELS = ['viewer', 'operator', 'admin'] as const

function Notice({ tone, children }: { tone: 'warn' | 'error' | 'ok'; children: React.ReactNode }) {
  const color = {
    warn: 'border-l-amber-400 text-amber-300',
    error: 'border-l-rose-400 text-rose-300',
    ok: 'border-l-emerald-400 text-emerald-300',
  }[tone]
  return (
    <div className={`rounded-lg border border-surface-border border-l-2 bg-surface-raised px-3 py-2 text-sm flex gap-2 ${color}`}>
      {tone === 'warn' && <TriangleAlert size={14} className="shrink-0 mt-1" />}
      <div className="min-w-0 break-words">{children}</div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="text-xs text-slate-400 block mb-1">{children}</label>
}

export function SecurityPage() {
  const { t } = useTranslation('security')
  const auth = useAuth((s) => s.status)
  const refreshAuth = useAuth((s) => s.refresh)

  const [error, setError] = useState<string | null>(null)
  const [settings, setSettings] = useState<SecuritySettings | null>(null)
  const [origins, setOrigins] = useState('')
  const [users, setUsers] = useState<UserOut[]>([])
  const [tokens, setTokens] = useState<TokenOut[]>([])
  const [created, setCreated] = useState<TokenCreated | null>(null)
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : t('failed'))

  const [newUser, setNewUser] = useState({ name: '', password: '', level: 'operator' as Level })
  const [newToken, setNewToken] = useState({ name: '', level: 'operator' as Level, days: '' })
  const [pw, setPw] = useState({ current: '', next: '' })
  const [pwDone, setPwDone] = useState(false)

  const enforced = auth?.enforced ?? false
  const isAdmin = auth?.level === 'admin'
  const insecure = isInsecureTransport(auth)
  const adminCount = users.filter((u) => u.level === 'admin').length

  const load = useCallback(async () => {
    try {
      const s = await api.getSettings()
      setSettings(s)
      setOrigins(s.allowed_origins.join('\n'))
      if (isAdmin) {
        setUsers(await api.listUsers())
        setTokens(await api.listTokens())
      }
    } catch (e) {
      fail(e)
    }
  }, [isAdmin])   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load() }, [load])

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      await refreshAuth()
      await load()
    } catch (e) {
      fail(e)
    }
  }

  const saveSettings = (patch: Partial<SecuritySettings>) => settings && run(async () => {
    setSettings(await api.putSettings({ ...settings, ...patch }))
  })

  const addUser = () => run(async () => {
    await api.createUser(newUser.name, newUser.password, newUser.level)
    setNewUser({ name: '', password: '', level: 'operator' })
  })

  const resetPassword = (name: string) => {
    const password = window.prompt(t('users.promptPassword', { name }))
    if (password) void run(() => api.updateUser(name, { password }))
  }

  const removeUser = (name: string) => {
    if (window.confirm(t('users.confirmDelete', { name }))) void run(() => api.deleteUser(name))
  }

  const addToken = () => run(async () => {
    setCreated(await api.createToken(newToken.name, newToken.level, newToken.days ? Number(newToken.days) : null))
    setNewToken({ name: '', level: 'operator', days: '' })
  })

  const savePassword = () => run(async () => {
    await api.changeOwnPassword(pw.current, pw.next)
    setPw({ current: '', next: '' })
    setPwDone(true)
  })

  const fmtDate = (iso: string | null) => (iso ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso)) : '—')

  return (
    <Page width="medium" className="space-y-4">
      <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
      <p className="text-xs text-slate-500">{t('intro')}</p>

      {error && <Notice tone="error">{error}</Notice>}
      {insecure && <Notice tone="warn">{t('insecure')}</Notice>}
      {!enforced && <Notice tone="warn">{t('open')}</Notice>}

      {/* First account: turns sign-in on. */}
      {!enforced && (
        <Card title={t('first.title')} className="p-4 space-y-3">
          <p className="text-xs text-slate-500">{t('first.hint')}</p>
          <div>
            <Label>{t('users.name')}</Label>
            <Input value={newUser.name} autoComplete="username" onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} />
          </div>
          <div>
            <Label>{t('users.password')}</Label>
            <Input type="password" value={newUser.password} autoComplete="new-password"
                   onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
            <p className="text-xs text-slate-600 mt-1">{t('users.passwordHint')}</p>
          </div>
          <Button disabled={!newUser.name || newUser.password.length < 8} onClick={addUser}>{t('first.create')}</Button>
        </Card>
      )}

      {enforced && auth?.kind === 'user' && (
        <Card title={t('me.title')} className="p-4 space-y-3">
          <p className="text-xs text-slate-500">{t('me.signedIn', { name: auth.name, level: t(`level.${auth.level}`) })}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>{t('me.current')}</Label>
              <Input type="password" value={pw.current} autoComplete="current-password"
                     onChange={(e) => { setPw({ ...pw, current: e.target.value }); setPwDone(false) }} />
            </div>
            <div>
              <Label>{t('me.new')}</Label>
              <Input type="password" value={pw.next} autoComplete="new-password"
                     onChange={(e) => { setPw({ ...pw, next: e.target.value }); setPwDone(false) }} />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" disabled={!pw.current || pw.next.length < 8} onClick={savePassword}>{t('me.change')}</Button>
            {pwDone && <span className="text-xs text-emerald-300">{t('me.changed')}</span>}
          </div>
        </Card>
      )}

      {enforced && !isAdmin && <Notice tone="warn">{t('adminOnly')}</Notice>}

      {enforced && isAdmin && settings && (
        <>
          <Card title={t('guest.title')} className="p-4 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">{t('guest.hint')}</p>
              <ToggleSwitch checked={settings.guest_enabled} label={t('guest.title')}
                            onChange={() => void saveSettings({ guest_enabled: !settings.guest_enabled })} />
            </div>
          </Card>

          <Card title={t('users.title')} className="p-4 space-y-4">
            <p className="text-xs text-slate-500">{t('users.hint')}</p>
            <ul className="divide-y divide-surface-border">
              {users.map((u) => (
                <li key={u.name} className="py-2 flex flex-wrap items-center gap-3">
                  <span className="font-mono text-sm text-slate-200 flex-1 min-w-24">{u.name}</span>
                  {u.level === 'admin' && adminCount <= 1 ? (
                    <span className="label-caps text-slate-400" title={t('users.lastAdmin')}>{t('level.admin')}</span>
                  ) : (
                    <PillGroup options={LEVELS} value={u.level} formatLabel={(l) => t(`level.${l}`)}
                               onChange={(level) => void run(() => api.updateUser(u.name, { level }))} />
                  )}
                  <Button size="sm" variant="ghost" onClick={() => resetPassword(u.name)}>{t('users.resetPassword')}</Button>
                  {!(u.level === 'admin' && adminCount <= 1) && (
                    <Button size="sm" variant="ghost" onClick={() => removeUser(u.name)}>{t('users.delete')}</Button>
                  )}
                </li>
              ))}
            </ul>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label>{t('users.name')}</Label>
                <Input value={newUser.name} onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} />
              </div>
              <div>
                <Label>{t('users.password')}</Label>
                <Input type="password" value={newUser.password} autoComplete="new-password"
                       onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
              </div>
            </div>
            <PillGroup options={LEVELS} value={newUser.level} formatLabel={(l) => t(`level.${l}`)}
                       onChange={(level) => setNewUser({ ...newUser, level })} />
            <Button variant="outline" disabled={!newUser.name || newUser.password.length < 8} onClick={addUser}>
              {t('users.add')}
            </Button>
          </Card>

          <Card title={t('tokens.title')} className="p-4 space-y-4">
            <p className="text-xs text-slate-500">{t('tokens.hint')}</p>
            {created && (
              <Notice tone="ok">
                <p>{t('tokens.created')}</p>
                <code className="block font-mono text-xs mt-1 select-all break-all">{created.token}</code>
              </Notice>
            )}
            <ul className="divide-y divide-surface-border">
              {tokens.map((k) => (
                <li key={k.id} className="py-2 flex flex-wrap items-center gap-3">
                  <div className="flex-1 min-w-32">
                    <p className="text-sm text-slate-200">{k.name}</p>
                    <p className="text-xs text-slate-500 font-mono">
                      {[
                        `${k.hint}…`,
                        t(`level.${k.level}`),
                        t('tokens.lastUsed', { date: fmtDate(k.last_used) }),
                        ...(k.expires ? [t('tokens.expires', { date: fmtDate(k.expires) })] : []),
                      ].join(' · ')}
                    </p>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => void run(() => api.deleteToken(k.id))}>{t('tokens.revoke')}</Button>
                </li>
              ))}
            </ul>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label>{t('tokens.name')}</Label>
                <Input value={newToken.name} onChange={(e) => setNewToken({ ...newToken, name: e.target.value })} />
              </div>
              <div>
                <Label>{t('tokens.days')}</Label>
                <Input type="number" min={1} value={newToken.days} placeholder={t('tokens.never')}
                       onChange={(e) => setNewToken({ ...newToken, days: e.target.value })} />
              </div>
            </div>
            <PillGroup options={LEVELS} value={newToken.level} formatLabel={(l) => t(`level.${l}`)}
                       onChange={(level) => setNewToken({ ...newToken, level })} />
            <Button variant="outline" disabled={!newToken.name} onClick={addToken}>{t('tokens.add')}</Button>
          </Card>

          <Card title={t('origins.title')} className="p-4 space-y-2">
            <p className="text-xs text-slate-500">{t('origins.hint')}</p>
            <textarea
              value={origins}
              rows={3}
              placeholder={t('origins.placeholder')}
              onChange={(e) => setOrigins(e.target.value)}
              className="w-full rounded-lg bg-surface border border-surface-border px-2.5 py-2 text-[13px] font-mono text-slate-200
                         placeholder:text-slate-500 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            />
            <Button variant="outline"
                    onClick={() => void saveSettings({ allowed_origins: origins.split('\n').map((o) => o.trim()).filter(Boolean) })}>
              {t('origins.save')}
            </Button>
          </Card>
        </>
      )}
    </Page>
  )
}
