import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Equipment } from './pages/Equipment'
import { Imaging } from './pages/Imaging'
import { Logs } from './pages/Logs'
import { Mount } from './pages/Mount'
import { Options } from './pages/Options'
import { Profiles } from './pages/Profiles'
import { LoginScreen } from './components/LoginScreen'
import { useAuth } from '@/auth'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { getPluginEntry } from '@/plugin-registry'
import { setLanguage } from '@/i18n'
import { setTheme } from '@/theme'

export function App() {
  const setPluginInfos = useStore((s) => s.setPluginInfos)
  const pluginInfos = useStore((s) => s.pluginInfos)

  const authStatus = useAuth((s) => s.status)
  const loginOpen = useAuth((s) => s.loginOpen)
  const refreshAuth = useAuth((s) => s.refresh)
  const ready = authStatus !== null && (!authStatus.enforced || authStatus.authenticated)

  useEffect(() => { void refreshAuth() }, [refreshAuth])

  useEffect(() => {
    if (!ready) return
    api.plugins.list()
      .then(setPluginInfos)
      .catch(() => {})
  }, [setPluginInfos, ready, authStatus?.name])

  useEffect(() => {
    if (!ready) return
    api.settings.get()
      .then((s) => {
        setLanguage(s.language ?? 'en')
        setTheme(s.theme ?? 'midnight')
      })
      .catch(() => {})
  }, [ready, authStatus?.name])

  const enabledPlugins = pluginInfos.filter((p) => p.enabled)

  if (authStatus === null) return null
  if (!ready || loginOpen) return <LoginScreen />

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/imaging" replace />} />
          <Route path="/equipment" element={<Equipment />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/imaging" element={<Imaging />} />
          <Route path="/imaging/:deviceId" element={<Imaging />} />
          <Route path="/mount" element={<Mount />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/options" element={<Options />} />
          {enabledPlugins.map((p) => {
            const entry = getPluginEntry(p.id)
            if (!entry) return null
            return (
              <Route
                key={p.id}
                path={entry.to}
                element={<entry.Component />}
              />
            )
          })}
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
