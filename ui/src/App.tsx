import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Equipment } from './pages/Equipment'
import { Imaging } from './pages/Imaging'
import { Logs } from './pages/Logs'
import { Mount } from './pages/Mount'
import { Options } from './pages/Options'
import { Profiles } from './pages/Profiles'

export function App() {
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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
