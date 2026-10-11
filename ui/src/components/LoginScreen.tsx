import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TriangleAlert } from 'lucide-react'
import { isInsecureTransport, useAuth } from '@/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function LoginScreen() {
  const { t } = useTranslation()
  const status = useAuth((s) => s.status)
  const login = useAuth((s) => s.login)
  const openLogin = useAuth((s) => s.openLogin)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.failed'))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-dvh bg-surface text-slate-200 flex items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm border border-surface-border rounded-[10px] bg-surface-raised p-5 space-y-4">
        <div className="flex items-center gap-3">
          <img src="/favicon-32x32.png" alt="" className="h-6 w-6" />
          <h1 className="text-lg font-semibold text-slate-100">{t('auth.title')}</h1>
        </div>

        {isInsecureTransport(status) && (
          <div className="flex gap-2 rounded-lg border border-surface-border border-l-2 border-l-amber-400 bg-surface px-3 py-2 text-xs text-amber-300">
            <TriangleAlert size={14} className="shrink-0 mt-0.5" />
            <span>{t('auth.insecure')}</span>
          </div>
        )}

        <div>
          <label className="text-xs text-slate-400 block mb-1" htmlFor="login-user">{t('auth.username')}</label>
          <Input id="login-user" value={username} autoFocus autoComplete="username" autoCapitalize="none"
                 onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1" htmlFor="login-pass">{t('auth.password')}</label>
          <Input id="login-pass" type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} />
        </div>

        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}

        <div className="flex gap-2">
          <Button type="submit" disabled={busy || !username || !password} className="flex-1">
            {busy ? t('auth.signingIn') : t('auth.signIn')}
          </Button>
          {status?.authenticated && (
            <Button type="button" variant="outline" onClick={() => openLogin(false)}>{t('auth.cancel')}</Button>
          )}
        </div>
      </form>
    </div>
  )
}
