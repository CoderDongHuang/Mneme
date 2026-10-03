import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
const AuthPage = lazy(() => import('./pages/AuthPage'))
const ChatPage = lazy(() => import('./pages/ChatPage'))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'))
const MemoryPage = lazy(() => import('./pages/MemoryPage'))
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const LegalPage = lazy(() => import('./pages/LegalPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const TasksPage = lazy(() => import('./pages/TasksPage'))
const RecoveryPage = lazy(() => import('./pages/RecoveryPage'))
const PrivacyPage = lazy(() => import('./pages/PrivacyPage'))
const OperationsPage = lazy(() => import('./pages/OperationsPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))

export default function App() {
  return (
    <Suspense fallback={<p className="loading-state" role="status">加载中...</p>}><Routes>
      <Route path="/auth" element={<AuthPage />} />
      <Route path="/legal/:document" element={<LegalPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/recovery" element={<RecoveryPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/operations" element={<OperationsPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes></Suspense>
  )
}
