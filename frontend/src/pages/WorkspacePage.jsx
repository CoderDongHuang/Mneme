import { lazy, Suspense } from 'react'
import ChatPage from './ChatPage'
import LoadingState from '../components/LoadingState'

const WorkspaceTools = lazy(() => import('../components/WorkspaceTools'))

export default function WorkspacePage() {
  return <ChatPage workspace renderTools={mode => <Suspense fallback={<LoadingState />}><WorkspaceTools key={mode} initialMode={mode} /></Suspense>} />
}
