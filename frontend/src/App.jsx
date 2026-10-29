import { t, useI18n } from './i18n'
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import AdminRoute from './components/AdminRoute'
const ReviewPage = lazy(() => import('./pages/ReviewPage'))
const QuizPage = lazy(() => import('./pages/QuizPage'))
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
  useI18n()
  return (
    <><div hidden={import.meta.env.VITE_DEMO_MODE !== 'true'} className="demo-banner" role="note">{t("离线演示 · 无外部模型调用 · 回答为原文摘录，推理与 AI 测验需配置模型")}</div><Suspense fallback={<p className="loading-state" role="status">{t("加载中...")}</p>}><Routes>
      <Route path="/auth" element={<AuthPage />} />
      <Route path="/legal/:document" element={<LegalPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/quiz" element={<QuizPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/recovery" element={<RecoveryPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route element={<AdminRoute />}><Route path="/operations" element={<OperationsPage />} /></Route>
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes></Suspense></>
  )
}
