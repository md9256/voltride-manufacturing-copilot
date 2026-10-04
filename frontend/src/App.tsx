import { NavLink, Outlet, useNavigation } from 'react-router'
import { HealthIndicator } from './components/HealthIndicator'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/bom', label: 'BOM explorer', end: false },
  { to: '/planner', label: 'Planner', end: false },
]

export default function App() {
  // While a lazy page's code loads, the router keeps the old page and reports "loading".
  const navigating = useNavigation().state === 'loading'
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <div>
              <p className="text-sm font-semibold leading-tight">VoltRide Systems</p>
              <p className="text-xs leading-tight text-slate-500">Manufacturing Copilot</p>
            </div>
          </div>
          <nav className="order-last flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto sm:flex-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap ${
                    isActive ? 'bg-teal-50 text-teal-800' : 'text-slate-600 hover:bg-slate-100'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <HealthIndicator />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className={navigating ? 'opacity-60 transition-opacity' : undefined}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
