import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import App from './App.tsx'
import './index.css'

// Pages are code-split with the router's own lazy loading: the chart library
// loads only for the dashboard and React Flow only for the BOM explorer.
const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    hydrateFallbackElement: <div />,
    children: [
      { index: true, lazy: async () => ({ Component: (await import('./pages/DashboardPage')).DashboardPage }) },
      { path: 'bom', lazy: async () => ({ Component: (await import('./pages/BomExplorerPage')).BomExplorerPage }) },
      { path: 'planner', lazy: async () => ({ Component: (await import('./pages/PlannerPage')).PlannerPage }) },
      { path: 'intake', lazy: async () => ({ Component: (await import('./pages/IntakePage')).IntakePage }) },
      { path: 'audit', lazy: async () => ({ Component: (await import('./pages/AuditPage')).AuditPage }) },
      { path: '*', lazy: async () => ({ Component: (await import('./pages/NotFoundPage')).NotFoundPage }) },
    ],
  },
])

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // ERP data changes slowly; avoid refetching on every tab focus.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
