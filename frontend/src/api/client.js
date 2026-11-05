import { validChatEvent } from './chatStreamContract'
import { matchesSchema } from './schemaContract'
import resultSchema from '../../../contracts/gateway-result.schema.json'
import { validDocumentPreview } from '../features/knowledge/previewValidation'
import { t } from '../i18n'

const API_BASE = '/api/v1'

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function randomHex(bytes) {
  const values = new Uint8Array(bytes)
  crypto.getRandomValues(values)
  return Array.from(values, (value) => value.toString(16).padStart(2, '0')).join('')
}

export function createTraceparent() {
  return `00-${randomHex(16)}-${randomHex(8)}-01`
}

function authHeaders(extra = {}) {
  return { traceparent: createTraceparent(), ...extra }
}

const rawJsonPaths = new Set(['/health', '/health/config', '/health/providers/check'])
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)

function errorMessage(payload, fallback) {
  return [payload?.message, payload?.detail, payload?.error?.message]
    .find(value => typeof value === 'string' && value.trim()) || fallback
}

function responseError(response, payload) {
  return new ApiError(errorMessage(payload, httpErrorMessage(response)), response.status, payload)
}

async function parseResponse(response, path) {
  if (response.status === 401) window.dispatchEvent(new Event('mneme:unauthorized'))
  let payload
  try { payload = await response.json() } catch (error) {
    if (error?.name === 'AbortError') throw error
    if (!response.ok) throw responseError(response, null)
    throw new ApiError('服务返回的数据格式异常，请刷新核实后再操作', response.status, { code: 'INVALID_API_RESPONSE' })
  }
  if (!response.ok) throw responseError(response, payload)
  if (matchesSchema(resultSchema, payload)) {
    if (payload.code !== 200) {
      if (payload.code === 401) window.dispatchEvent(new Event('mneme:unauthorized'))
      throw responseError(response, payload)
    }
    // null is a successful void result, not a signal to return the envelope.
    return payload.data
  }
  // Health probes intentionally return bare objects. Keep this exception tied
  // to their routes, never to a caller-controlled "skip validation" option.
  if (rawJsonPaths.has(path.split('?')[0]) && record(payload) && !Object.hasOwn(payload, 'code')) return payload
  throw new ApiError('服务返回的数据格式异常，请刷新核实后再操作', response.status, { code: 'INVALID_API_RESPONSE' })
}

function httpErrorMessage(response) {
  if (response.status === 429) {
    const retryAfter = response.headers?.get('Retry-After')
    const seconds = Number(retryAfter)
    return retryAfter && Number.isInteger(seconds) && seconds > 0
      ? `请求过于频繁，请在 ${seconds} 秒后重试`
      : '请求过于频繁，请稍后重试'
  }
  if ([502, 503, 504].includes(response.status)) return '服务暂时不可用，请稍后重试'
  return `请求失败（HTTP ${response.status}），请稍后重试`
}

export async function api(path, options = {}) {
  const isForm = options.body instanceof FormData
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: 'include',
      headers: authHeaders({
        ...(!isForm && options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      }),
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('无法连接服务，请确认 Mneme 服务已启动后重试', 0, { cause: error?.message })
  }
  return parseResponse(response, path)
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
    throw new ApiError(errorMessage(error, '无法建立流式连接'), response.status, error)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = 'message'
  let dataLines = []
  let completed = false
  let terminalStatus = 'completed'
  const dispatch = () => {
    if (!dataLines.length) { eventName = 'message'; return }
    const raw = dataLines.join('\n')
    dataLines = []
    const name = eventName
    eventName = 'message'
    let data
    try { data = JSON.parse(raw) } catch { throw new ApiError('回答流格式异常，请重试', 200, { code: 'INVALID_CHAT_EVENT' }) }
    if (!validChatEvent(name, data)) throw new ApiError('回答流格式异常，请重试', 200, { code: 'INVALID_CHAT_EVENT' })
    onEvent(name, data)
    if (name === 'error') throw new ApiError(data.message || '回答生成失败', 200, data)
    if (name === 'done') completed = true
    if (name === 'stopped') { completed = true; terminalStatus = 'stopped' }
  }
  const consumeLine = (line) => {
    line = line.replace(/\r$/, '')
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    } else if (!line) {
      dispatch()
    }
  }
  try {
    while (!completed) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        consumeLine(line)
        if (completed) break
      }
    }
    if (!completed) {
      buffer += decoder.decode()
      if (buffer) buffer.split('\n').forEach(consumeLine)
      dispatch()
    }
    if (!completed) throw new ApiError('连接已中断，回答未完成，请重试', 0)
    return { status: terminalStatus }
  } finally {
    try { await reader.cancel?.() } catch { /* the stream may already be closed */ }
    reader.releaseLock?.()
  }
}

export const endpoints = {
  stopChat: (body) => api('/chat/stop', { method: 'POST', body: JSON.stringify(body) }),
  preferences: () => api('/settings/preferences'),
  savePreferences: (body) => api('/settings/preferences', { method: 'PUT', body: JSON.stringify(body) }),
  modelSettings: (options) => api('/settings/models', options),
  saveModelSettings: (body, options) => api('/settings/models', { ...options, method: 'PUT', body: JSON.stringify(body) }),
  testModelSettings: (body, options) => api('/settings/models/test', { ...options, method: 'POST', body: JSON.stringify(body) }),
  authSessions: () => api('/profile/sessions'),
  revokeAuthSession: (id) => api(`/profile/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  quizDraft: (id, options) => api(`/workspace/quizzes/${id}/draft`, options),
  saveQuizDraft: (id, body) => api(`/workspace/quizzes/${id}/draft`, { method: 'PUT', body: JSON.stringify(body) }),
  quizAttempts: (id, options) => api(`/workspace/quizzes/${id}/attempts`, options),
  reportQuestion: (id, body) => api(`/workspace/quizzes/${id}/reports`, { method: 'POST', body: JSON.stringify(body) }),
  login: (body) => api('/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  register: (body) => api('/auth/register', { method: 'POST', body: JSON.stringify(body) }),
  logout: () => api('/auth/logout', { method: 'POST' }),
  resetPassword: (body) => api('/auth/reset-password', { method: 'POST', body: JSON.stringify(body) }),
  requestPasswordReset: (body) => api('/auth/password-reset/request', { method: 'POST', body: JSON.stringify(body) }),
  confirmPasswordReset: (body) => api('/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify(body) }),
  profile: () => api('/profile'),
  updateProfile: (body) => api('/profile', { method: 'PATCH', body: JSON.stringify(body) }),
  requestEmailVerification: (email) => api('/profile/email-verification/request', { method: 'POST', body: JSON.stringify({ email }) }),
  confirmEmailVerification: (token) => api('/profile/email-verification/confirm', { method: 'POST', body: JSON.stringify({ token }) }),
  changePassword: (body) => api('/profile/password', { method: 'POST', body: JSON.stringify(body) }),
  deleteAccount: () => api('/profile/account', { method: 'DELETE' }),
  uploadAvatar: (file) => {
    const form = new FormData()
    form.append('file', file)
    return api('/profile/avatar', { method: 'POST', body: form })
  },
  avatarUrl: () => `${API_BASE}/profile/avatar`,
  sessions: options => api('/sessions', options),
  createSession: (title = '新对话') => api('/sessions', { method: 'POST', body: JSON.stringify({ title }) }),
  sessionMessages: (id) => api(`/sessions/${id}/messages`),
  deleteSession: (id) => api(`/sessions/${id}`, { method: 'DELETE' }),
  renameSession: (id, title) => api(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  knowledgeBases: (options) => api('/knowledge/base/list', options),
  createKnowledgeBase: (body) => api('/knowledge/base', { method: 'POST', body: JSON.stringify(body) }),
  deleteKnowledgeBase: (id) => api(`/knowledge/base/${id}`, { method: 'DELETE' }),
  documents: (kbId, options) => api(`/knowledge/base/${kbId}/documents`, options),
  documentStatus: (id) => api(`/knowledge/document/${id}/status`),
  deleteDocument: (id) => api(`/knowledge/document/${id}`, { method: 'DELETE' }),
  reparseDocument: (id) => api(`/knowledge/document/${id}/reparse`, { method: 'POST' }),
  repairDocumentIndex: (id) => api(`/knowledge/document/${id}/repair-index`, { method: 'POST' }),
  documentVersions: (id) => api(`/knowledge/document/${id}/versions`),
  restoreDocumentVersion: (id, version) => api(`/knowledge/document/${id}/versions/${version}/restore`, { method: 'POST' }),
  replaceDocument: (id, file) => {
    const form = new FormData()
    form.append('file', file)
    return api(`/knowledge/document/${id}/replace`, { method: 'POST', body: form })
  },
  uploadDocument: (kbId, file, { signal, requestId } = {}) => {
    const form = new FormData()
    form.append('kbId', kbId)
    form.append('file', file)
    if (requestId) form.append('requestId', requestId)
    return api('/knowledge/document/upload', { method: 'POST', body: form, signal })
  },
  cancelUpload: (kbId, requestId) => api(`/knowledge/document/uploads/${encodeURIComponent(requestId)}/cancel?kbId=${encodeURIComponent(kbId)}`, { method: 'POST' }),
  memory: () => api('/memory'),
  pendingMemories: (options) => api('/memory/pending', options),
  writeMemory: (body) => api('/memory/write', { method: 'POST', body: JSON.stringify(body) }),
  confirmMemory: (body) => api('/memory/confirm', { method: 'POST', body: JSON.stringify(body) }),
  documentPreview: async (id, sha256) => {
    const preview = await api(`/workspace/documents/${id}/preview${sha256 ? `?sha256=${encodeURIComponent(sha256)}` : ''}`)
    if (!validDocumentPreview(preview, id, sha256)) throw new ApiError(t('文档预览格式无效，请重试或重新解析'), 200, { code: 'INVALID_DOCUMENT_PREVIEW' })
    return preview
  },
  documentTags: (id) => api(`/workspace/documents/${id}/tags`),
  setDocumentTags: (id, tags) => api(`/workspace/documents/${id}/tags`, { method: 'PUT', body: JSON.stringify(tags) }),
  tasks: ({ signal } = {}) => api('/workspace/tasks', { signal }),
  operations: ({ signal } = {}) => api('/workspace/operations?limit=200', { signal }),
  cancelTask: (id, { signal } = {}) => api(`/workspace/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST', signal }),
  retryTask: (id, { signal } = {}) => api(`/workspace/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST', signal }),
  retrievalDebug: (kbId, query, topK = 6, filters = {}) => {
    const params = new URLSearchParams({ kbId, query, topK })
    ;(filters.selected_document_ids || []).forEach(id => params.append('documentIds', id))
    ;(filters.tags || []).forEach(tag => params.append('tags', tag))
    if (filters.date_from) params.set('dateFrom', filters.date_from)
    if (filters.date_to) params.set('dateTo', filters.date_to)
    return api(`/workspace/retrieval/debug?${params}`)
  },
  plans: (options) => api('/workspace/plans', options),
  metrics: () => api('/workspace/metrics'),
  metricHistory: (days = 30) => api(`/workspace/metrics/history?days=${days}`),
  createPlan: (body) => api('/workspace/plans', { method: 'POST', body: JSON.stringify(body) }),
  reviews: (options) => api('/workspace/reviews', options),
  reviewCard: (id, rating) => api(`/workspace/reviews/${id}`, { method: 'POST', body: JSON.stringify({ rating }) }),
  quizzes: options => api('/workspace/quizzes', options),
  generateQuiz: (body) => api('/workspace/quizzes/generate', { method: 'POST', body: JSON.stringify(body) }),
  submitQuiz: (id, answers, requestId) => api(`/workspace/quizzes/${id}/submit`, { method: 'POST', body: JSON.stringify({ answers, request_id: requestId }) }),
  managedMemories: (options) => api('/workspace/memories', options),
  updateManagedMemory: (id, body) => api(`/workspace/memories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteManagedMemory: (id) => api(`/workspace/memories/${id}`, { method: 'DELETE' }),
  memoryVersions: (id, options) => api(`/workspace/memories/${id}/versions`, options),
  restoreMemory: (id, version) => api(`/workspace/memories/${id}/restore`, { method: 'POST', body: JSON.stringify({ version }) }),
  branches: () => api('/workspace/branches'),
  healthConfig: (options) => api('/health/config', options),
  checkProviders: () => api('/health/providers/check', { method: 'POST' }),
  notifications: (options) => api('/notifications', options),
  createBranch: (body) => api('/workspace/branches', { method: 'POST', body: JSON.stringify(body) }),
  compareBranch: (id) => api(`/workspace/branches/${id}/compare`),
  importData: (body) => api('/workspace/import', { method: 'POST', body: JSON.stringify(body) }),
  previewArchive: (file, scope = 'all', options = {}) => {
    const form = new FormData()
    form.append('archive', file)
    form.append('scope', scope)
    return api('/workspace/import/archive/preview', { method: 'POST', body: form, signal: options.signal })
  },
  importArchive: (file, scope = 'all', sha256, options = {}) => {
    const form = new FormData()
    form.append('archive', file)
    form.append('scope', scope)
    if (sha256) form.append('sha256', sha256)
    return api('/workspace/import/archive', { method: 'POST', body: form, signal: options.signal })
  },
}

export function openNotificationStream(onEvent, options = {}) {
  const EventSourceClass = options.EventSourceClass || EventSource
  const schedule = options.setTimeout || globalThis.setTimeout
  const cancel = options.clearTimeout || globalThis.clearTimeout
  const baseDelayMs = options.baseDelayMs ?? 1_000
  const maxDelayMs = options.maxDelayMs ?? 30_000
  let source = null
  let reconnectTimer = null
  let reconnectAttempt = 0
  let closed = false

  const connect = () => {
    if (closed) return
    source = new EventSourceClass(`${API_BASE}/notifications/stream`, { withCredentials: true })
    source.onopen = () => { reconnectAttempt = 0 }
    source.addEventListener('task', (event) => {
      reconnectAttempt = 0
      try { onEvent(JSON.parse(event.data)) } catch { /* ignore malformed server events */ }
    })
    source.onerror = () => {
      source?.close()
      source = null
      onEvent(null)
      if (closed || reconnectTimer !== null) return
      const delay = Math.min(maxDelayMs, baseDelayMs * (2 ** reconnectAttempt))
      reconnectAttempt += 1
      reconnectTimer = schedule(() => {
        reconnectTimer = null
        connect()
      }, delay)
    }
  }

  connect()
  return {
    close() {
      closed = true
      source?.close()
      source = null
      if (reconnectTimer !== null) cancel(reconnectTimer)
      reconnectTimer = null
    },
  }
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

export async function downloadWorkspaceArchive({ signal } = {}) {
  const response = await fetch(`${API_BASE}/workspace/export/archive`, { credentials: 'include', signal })
  if (!response.ok) throw new ApiError('归档导出失败', response.status)
  const blob = await response.blob()
  signal?.throwIfAborted()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'mneme-workspace.zip'
  anchor.click()
  URL.revokeObjectURL(url)
  return { bytes: blob.size }
}

export function documentFileUrl(id, page, sha256) {
  const anchor = page ? `#page=${encodeURIComponent(page)}` : ''
  return `${API_BASE}/workspace/documents/${encodeURIComponent(id)}/file${sha256 ? `?sha256=${encodeURIComponent(sha256)}` : ''}${anchor}`
}
