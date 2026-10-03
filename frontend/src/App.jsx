import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import AuthPage from './pages/AuthPage'
import ChatPage from './pages/ChatPage'
import KnowledgePage from './pages/KnowledgePage'
import MemoryPage from './pages/MemoryPage'
import WorkspacePage from './pages/WorkspacePage'
import ProfilePage from './pages/ProfilePage'
import LegalPage from './pages/LegalPage'
import SettingsPage from './pages/SettingsPage'
import TasksPage from './pages/TasksPage'
import RecoveryPage from './pages/RecoveryPage'
import PrivacyPage from './pages/PrivacyPage'
import OperationsPage from './pages/OperationsPage'

export default function App() {
  return (
    <Routes>
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
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  )
}
