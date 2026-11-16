import { createBrowserRouter, Navigate } from 'react-router-dom'
import { ProtectedRoute, PublicOnlyRoute } from '../auth/RouteGuards'
import AppShell from '../components/layout/AppShell'
import CodeChatPage from '../pages/CodeChatPage'
import CodeSearchPage from '../pages/CodeSearchPage'
import DashboardPage from '../pages/DashboardPage'
import LoginPage from '../pages/LoginPage'
import RegisterPage from '../pages/RegisterPage'
import RepositoriesPage from '../pages/RepositoriesPage'
import SettingsPage from '../pages/SettingsPage'

export const router = createBrowserRouter([
  {
    element: <PublicOnlyRoute />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
    ],
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <DashboardPage /> },
          { path: '/repositories', element: <RepositoriesPage /> },
          { path: '/search', element: <CodeSearchPage /> },
          { path: '/assistant', element: <CodeChatPage /> },
          { path: '/settings', element: <SettingsPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
