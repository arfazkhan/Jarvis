import { BrowserRouter, Routes, Route, Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Login from './components/Login'
import Overview from './pages/Overview'
import Operations from './pages/Operations'
import RoundDetail from './pages/RoundDetail'
import CheckItem from './pages/CheckItem'
import Issues from './pages/Issues'
import Assets from './pages/Assets'
import People from './pages/People'
import Intelligence from './pages/Intelligence'
import FieldHome from './pages/FieldHome'
import FieldRound from './pages/FieldRound'
import Onboard from './components/Onboard'
import { AuthProvider, useAuth } from './lib/AuthContext'
import { BuildingProvider, useBuilding } from './lib/BuildingContext'

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  )
}

function Center({ children, className = 'text-text-faint' }) {
  return <div className={`h-screen w-full bg-bg flex items-center justify-center text-sm ${className}`}>{children}</div>
}

function AuthGate() {
  const { status, error, retry } = useAuth()
  if (status === 'checking') return <Center>Loading…</Center>
  if (status === 'login') {
    if (error) {
      return (
        <div className="h-screen w-full bg-bg flex flex-col items-center justify-center gap-3 text-sm">
          <div className="text-red">Could not reach AllGud API: {error.message}</div>
          <button onClick={retry} className="text-gold">Retry</button>
        </div>
      )
    }
    return <Login />
  }
  return (
    <BuildingProvider>
      <Shell />
    </BuildingProvider>
  )
}

function Shell() {
  const { loading, error, buildings } = useBuilding()

  if (loading) return <Center>Loading buildings…</Center>
  if (error) return <Center className="text-red">Could not reach AllGud API: {error.message}</Center>
  if (!buildings.length) {
    return (
      <div className="h-screen w-full bg-bg flex flex-col items-center justify-center gap-6">
        <div className="text-center">
          <div className="font-serif text-2xl text-text mb-1">No buildings yet</div>
          <div className="text-sm text-text-faint">Seed a starter checklist pack to get started.</div>
        </div>
        <Onboard embedded />
      </div>
    )
  }

  return (
    <BrowserRouter>
      <Routes>
        {/* Field app — full screen, no sidebar (technician's phone) */}
        <Route path="/field" element={<FieldHome />} />
        <Route path="/field/run/:rid" element={<FieldRound />} />

        {/* Console — manager, with sidebar */}
        <Route element={<ConsoleLayout />}>
          <Route path="/" element={<Overview />} />
          <Route path="/operations" element={<Operations />} />
          <Route path="/operations/round/:rid" element={<RoundDetail />} />
          <Route path="/operations/round/:rid/check/:itemIndex" element={<CheckItem />} />
          <Route path="/issues" element={<Issues />} />
          <Route path="/assets" element={<Assets />} />
          <Route path="/people" element={<People />} />
          <Route path="/intelligence" element={<Intelligence />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

function ConsoleLayout() {
  return (
    <div className="flex h-screen w-full bg-bg text-text font-sans overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
