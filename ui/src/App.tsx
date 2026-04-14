import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Equipment } from './pages/Equipment'
import { Imaging } from './pages/Imaging'
import { Logs } from './pages/Logs'
import { Mount } from './pages/Mount'
import { Options } from './pages/Options'
import { Profiles } from './pages/Profiles'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { getPluginEntry } from '@/plugin-registry'

export function App() {
  const setPluginInfos = useStore((s) => s.setPluginInfos)
  const pluginInfos = useStore((s) => s.pluginInfos)

  useEffect(() => {
    api.plugins.list()
      .then(setPluginInfos)
      .catch(() => {})
  }, [setPluginInfos])

  const enabledPlugins = pluginInfos.filter((p) => p.enabled)

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/imaging" replace />} />
          <Route path="/equipment" element={<Equipment />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/imaging" element={<Imaging />} />
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
