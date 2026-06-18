import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Overview from './pages/Overview'
import Operations from './pages/Operations'
import RoundDetail from './pages/RoundDetail'
import CheckItem from './pages/CheckItem'
import Issues from './pages/Issues'
import Assets from './pages/Assets'
import People from './pages/People'
import Intelligence from './pages/Intelligence'
import Onboard from './components/Onboard'
import { BuildingProvider, useBuilding } from './lib/BuildingContext'

export default function App() {
  return (
    <BuildingProvider>
      <Shell />
    </BuildingProvider>
  )
}

function Shell() {
  const { loading, error, buildings } = useBuilding()

  if (loading) {
    return (
      <div className="h-screen w-full bg-bg text-text-faint flex items-center justify-center text-sm">
        Loading buildings…
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-screen w-full bg-bg text-red flex items-center justify-center text-sm">
        Could not reach AllGud API: {error.message}
      </div>
    )
  }

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
      <div className="flex h-screen w-full bg-bg text-text font-sans overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/operations" element={<Operations />} />
            <Route path="/operations/round/:rid" element={<RoundDetail />} />
            <Route path="/operations/round/:rid/check/:itemIndex" element={<CheckItem />} />
            <Route path="/issues" element={<Issues />} />
            <Route path="/assets" element={<Assets />} />
            <Route path="/people" element={<People />} />
            <Route path="/intelligence" element={<Intelligence />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
