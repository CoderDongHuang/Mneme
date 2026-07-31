const API_BASE = '/api/v1'

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function authHeaders(extra = {}) {
  return extra
}

async function parseResponse(response) {
  const payload = await response.json().catch(() => null)
  if (!response.ok || (payload && payload.code && payload.code !== 200)) {
    const message = payload?.message || payload?.detail || payload?.error?.message || '请求失败'
    if (response.status === 401) window.dispatchEvent(new Event('mneme:unauthorized'))
    throw new ApiError(message, response.status, payload)
  }
  return payload?.data ?? payload
}

export async function api(path, options = {}) {
  const isForm = options.body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
    headers: authHeaders({
      ...(!isForm && options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    }),
  })
  return parseResponse(response)
}

export async function streamChat(payload, { signal, onEvent }) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal,
    credentials: 'include',
  })
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({}))
    if (response.status === 401) window.dispatchEvent(new Event('mneme:unauthorized'))
    throw new ApiError(error.message || error?.error?.message || '无法建立流式连接', response.status, error)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = 'message'
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        const raw = line.slice(5).trim()
        if (!raw) continue
        let data
        try { data = JSON.parse(raw) } catch { data = { content: raw } }
        onEvent(eventName, data)
      } else if (!line.trim()) {
        eventName = 'message'
      }
    }
  }
}

export const endpoints = {
  login: (body) => api('/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  register: (body) => api('/auth/register', { method: 'POST', body: JSON.stringify(body) }),
  logout: () => api('/auth/logout', { method: 'POST' }),
  resetPassword: (body) => api('/auth/reset-password', { method: 'POST', body: JSON.stringify(body) }),
  requestPasswordReset: (body) => api('/auth/password-reset/request', { method: 'POST', body: JSON.stringify(body) }),
  confirmPasswordReset: (body) => api('/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify(body) }),
  profile: () => api('/profile'),
  updateProfile: (body) => api('/profile', { method: 'PATCH', body: JSON.stringify(body) }),
  changePassword: (body) => api('/profile/password', { method: 'POST', body: JSON.stringify(body) }),
  deleteAccount: () => api('/profile/account', { method: 'DELETE' }),
  uploadAvatar: (file) => {
    const form = new FormData()
    form.append('file', file)
    return api('/profile/avatar', { method: 'POST', body: form })
  },
  avatarUrl: () => `${API_BASE}/profile/avatar`,
  sessions: () => api('/sessions'),
  createSession: (title = '新对话') => api('/sessions', { method: 'POST', body: JSON.stringify({ title }) }),
  sessionMessages: (id) => api(`/sessions/${id}/messages`),
  deleteSession: (id) => api(`/sessions/${id}`, { method: 'DELETE' }),
  knowledgeBases: () => api('/knowledge/base/list'),
  createKnowledgeBase: (body) => api('/knowledge/base', { method: 'POST', body: JSON.stringify(body) }),
  deleteKnowledgeBase: (id) => api(`/knowledge/base/${id}`, { method: 'DELETE' }),
  documents: (kbId) => api(`/knowledge/base/${kbId}/documents`),
  documentStatus: (id) => api(`/knowledge/document/${id}/status`),
  uploadDocument: (kbId, file) => {
    const form = new FormData()
    form.append('kbId', kbId)
    form.append('file', file)
    return api('/knowledge/document/upload', { method: 'POST', body: form })
  },
  memory: () => api('/memory'),
  writeMemory: (body) => api('/memory/write', { method: 'POST', body: JSON.stringify(body) }),
  confirmMemory: (body) => api('/memory/confirm', { method: 'POST', body: JSON.stringify(body) }),
  documentPreview: (id) => api(`/workspace/documents/${id}/preview`),
  tasks: () => api('/workspace/tasks'),
  retryTask: (id) => api(`/workspace/tasks/${id}/retry`, { method: 'POST' }),
  retrievalDebug: (kbId, query, topK = 6) => api(`/workspace/retrieval/debug?kbId=${encodeURIComponent(kbId)}&query=${encodeURIComponent(query)}&topK=${topK}`),
  plans: () => api('/workspace/plans'),
  createPlan: (body) => api('/workspace/plans', { method: 'POST', body: JSON.stringify(body) }),
  reviews: () => api('/workspace/reviews'),
  reviewCard: (id, rating) => api(`/workspace/reviews/${id}`, { method: 'POST', body: JSON.stringify({ rating }) }),
  quizzes: () => api('/workspace/quizzes'),
  generateQuiz: (body) => api('/workspace/quizzes/generate', { method: 'POST', body: JSON.stringify(body) }),
  submitQuiz: (id, answers) => api(`/workspace/quizzes/${id}/submit`, { method: 'POST', body: JSON.stringify({ answers }) }),
  managedMemories: () => api('/workspace/memories'),
  updateManagedMemory: (id, body) => api(`/workspace/memories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteManagedMemory: (id) => api(`/workspace/memories/${id}`, { method: 'DELETE' }),
  branches: () => api('/workspace/branches'),
  createBranch: (body) => api('/workspace/branches', { method: 'POST', body: JSON.stringify(body) }),
  compareBranch: (id) => api(`/workspace/branches/${id}/compare`),
  importData: (body) => api('/workspace/import', { method: 'POST', body: JSON.stringify(body) }),
}

export async function downloadWorkspaceExport() {
  const response = await fetch(`${API_BASE}/workspace/export`, { credentials: 'include' })
  if (!response.ok) throw new ApiError('导出失败', response.status)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'mneme-export.json'
  anchor.click()
  URL.revokeObjectURL(url)
}
