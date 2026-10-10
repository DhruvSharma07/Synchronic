import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { DocumentPage } from './pages/DocumentPage'
import { Documents } from './pages/Documents'
import { Login } from './pages/Login'
import { useAuth } from './state/auth'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const status = useAuth((s) => s.status)
  const location = useLocation()
  if (status === 'loading') return <p className="muted center">Loading…</p>
  if (status === 'anon') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

export default function App() {
  const init = useAuth((s) => s.init)
  useEffect(() => {
    void init()
  }, [init])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<RequireAuth><Documents /></RequireAuth>} />
        <Route path="/d/:documentId" element={<RequireAuth><DocumentPage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
