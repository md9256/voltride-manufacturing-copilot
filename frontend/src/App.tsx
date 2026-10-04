import { HealthIndicator } from './components/HealthIndicator'
import { DashboardPage } from './pages/DashboardPage'

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <div>
              <p className="text-sm font-semibold leading-tight">VoltRide Systems</p>
              <p className="text-xs leading-tight text-slate-500">Manufacturing Copilot</p>
            </div>
          </div>
          <HealthIndicator />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <h1 className="mb-5 text-xl font-semibold">Production overview</h1>
        <DashboardPage />
      </main>
    </div>
  )
}
