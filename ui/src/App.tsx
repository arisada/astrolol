import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Equipment } from './pages/Equipment'
import { Imaging } from './pages/Imaging'
import { Options } from './pages/Options'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/imaging" replace />} />
          <Route path="/equipment" element={<Equipment />} />
          <Route path="/imaging" element={<Imaging />} />
          <Route path="/options" element={<Options />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
