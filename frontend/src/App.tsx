import { lazy, Suspense, useState } from 'react'
import { NavLink, Outlet, useNavigation } from 'react-router'
import { HealthIndicator } from './components/HealthIndicator'

// The assistant (and its Markdown renderer) loads on first open, then stays
// mounted so a reply keeps streaming while the panel is closed.
const ChatPanel = lazy(() => import('./components/chat/ChatPanel'))

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/bom', label: 'BOM explorer', end: false },
  { to: '/planner', label: 'Planner', end: false },
  { to: '/intake', label: 'Quote intake', end: false },
  { to: '/audit', label: 'Audit log', end: false },
]

export default function App() {
  // While a lazy page's code loads, the router keeps the old page and reports "loading".
  const navigating = useNavigation().state === 'loading'
  const [chatOpen, setChatOpen] = useState(false)
  const [chatLoaded, setChatLoaded] = useState(false)
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
          <div className="flex items-center gap-2">
            <HealthIndicator />
            <button
              type="button"
              onClick={() => {
                setChatLoaded(true)
                setChatOpen((o) => !o)
              }}
              className="rounded-full bg-teal-700 px-3.5 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-teal-800"
              aria-expanded={chatOpen}
            >
              Ask Copilot
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className={navigating ? 'opacity-60 transition-opacity' : undefined}>
          <Outlet />
        </div>
      </main>
      {chatLoaded && (
        <Suspense fallback={null}>
          <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
        </Suspense>
      )}
    </div>
  )
}
