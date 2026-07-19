import { lazy, Suspense } from 'react'
import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { LoaderCircle } from 'lucide-react'
import { AppShell } from './components/AppShell'
import { useAuth } from './lib/auth'

const AuthPage = lazy(() => import('./pages/AuthPage').then((module) => ({ default: module.AuthPage })))
const ChatPage = lazy(() => import('./pages/ChatPage').then((module) => ({ default: module.ChatPage })))
const ProjectPage = lazy(() => import('./pages/ProjectPage').then((module) => ({ default: module.ProjectPage })))
const ConsolePage = lazy(() => import('./pages/ConsolePage').then((module) => ({ default: module.ConsolePage })))
const AdminPage = lazy(() => import('./pages/AdminPage').then((module) => ({ default: module.AdminPage })))

function LoadingScreen() {
  return (
    <div className="route-loading">
      <LoaderCircle size={24} className="spin" />
      <span>加载研究空间…</span>
    </div>
  )
}

function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth()
  if (loading) return <LoadingScreen />
  return isAuthenticated ? <Outlet /> : <Navigate to="/login" replace />
}

function GuestRoute() {
  const { isAuthenticated, loading } = useAuth()
  if (loading) return <LoadingScreen />
  return isAuthenticated ? <Navigate to="/" replace /> : <Outlet />
}

function AdminRoute() {
  const { isAdmin, loading } = useAuth()
  if (loading) return <LoadingScreen />
  return isAdmin ? <Outlet /> : <Navigate to="/" replace />
}

function ShellRoute() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingScreen />}>
        <Outlet />
      </Suspense>
    </AppShell>
  )
}

function NotFound() {
  const { isAuthenticated } = useAuth()
  return (
    <main className="not-found">
      <p className="not-found-code">404</p>
      <h1>这条路径不存在</h1>
      <p>检查地址，或返回可访问的研究空间。</p>
      <Link className="ui-button ui-button-solid ui-button-md" to={isAuthenticated ? '/' : '/login'}>
        {isAuthenticated ? '返回研究空间' : '返回登录'}
      </Link>
    </main>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<GuestRoute />}>
        <Route
          path="/login"
          element={
            <Suspense fallback={<LoadingScreen />}>
              <AuthPage mode="login" />
            </Suspense>
          }
        />
        <Route
          path="/register"
          element={
            <Suspense fallback={<LoadingScreen />}>
              <AuthPage mode="register" />
            </Suspense>
          }
        />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route element={<ShellRoute />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/projects/new" element={<Navigate to="/" replace />} />
          <Route path="/console/:section" element={<ConsolePage />} />
          <Route path="/console" element={<Navigate to="/console/overview" replace />} />
          <Route element={<AdminRoute />}>
            <Route path="/admin/:section" element={<AdminPage />} />
            <Route path="/admin" element={<Navigate to="/admin/overview" replace />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
