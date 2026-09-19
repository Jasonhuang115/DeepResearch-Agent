import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { getAccess } from './api/client'
import './index.css'
import { LoginPage } from './pages/Login'
import { WorkspacePage } from './pages/Workspace'

const qc = new QueryClient()

function requireAuth() {
  if (!getAccess()) throw redirect({ to: '/login' })
}

const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: requireAuth,
  component: WorkspacePage,
})

const convRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/c/$conversationId',
  beforeLoad: requireAuth,
  component: WorkspacePage,
})

const router = createRouter({
  routeTree: rootRoute.addChildren([loginRoute, indexRoute, convRoute]),
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
