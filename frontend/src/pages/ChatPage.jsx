import { useFormatters } from '../hooks/useFormatters'
import { parseInstant } from '../utils/dates'
import { useDateFormatter } from '../hooks/useDateFormatter'
import { t, useI18n } from '../i18n'
import {
  ArrowUp, BookOpen, Check, ChevronDown, CircleStop, FileText, MessageSquarePlus,
  PanelLeftClose, PanelLeftOpen, Quote, Search, SlidersHorizontal, Sparkles, Trash2, X,
} from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { endpoints, streamChat } from '../api/client'
import { Modal } from '../components/ui'
import LoadingState from '../components/LoadingState'
import RetrievalFilters, { emptyFilters } from '../components/RetrievalFilters'
import useChatScroll from '../hooks/useChatScroll'
import logo from '../assets/mneme-logo.svg'
import '../styles/chat.css'
import '../styles/reference-chat.css'

const AnswerMarkdown = lazy(() => import('../components/AnswerMarkdown'))

function answerFailure(message) {
  const labels = {
    CLIENT_DISCONNECTED: '连接已中断，请重试', MODEL_TIMEOUT: '模型响应超时，请重试',
    MODEL_ERROR: '模型生成失败，请重试', GROUNDING_FAILED: '引用核验失败，请重试',
    MEMORY_FAILED: '记忆处理失败，请重试',
  }
  return message.error || t(Object.hasOwn(labels, message.errorCode) ? labels[message.errorCode] : '回答未完成，请重试')
}

export default function ChatPage({ renderTools, workspace = false }) {
  useI18n();
  const dates = useDateFormatter()
  const fmt = useFormatters()
  const navigate = useNavigate()
  const location = useLocation()
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyDate, setHistoryDate] = useState('')
  const [historyRange, setHistoryRange] = useState(0)
  const [historyNow] = useState(Date.now)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [toolMode, setToolMode] = useState(() => workspace && new URLSearchParams(window.location.search).has('document') ? 'reader' : null)
  useEffect(() => { if (workspace && new URLSearchParams(location.search).has('document')) setToolMode('reader') }, [workspace, location.search])
  const [renaming, setRenaming] = useState(null)
  const [renameBusy, setRenameBusy] = useState(false)
  const renameLock = useRef(false)
  const [narrow, setNarrow] = useState(window.innerWidth <= 1279)
  const [sessions, setSessions] = useState([])
  const [conversation, setConversation] = useState({ session: null, messages: [] })
  const { session: activeSession, messages } = conversation
  const setMessages = (update) => setConversation(current => ({ ...current, messages: typeof update === 'function' ? update(current.messages) : update }))
  const [switching, setSwitching] = useState(false)
  const selectionRef = useRef(0)
  const [knowledgeBases, setKnowledgeBases] = useState([])
  const [selectedKbIds, setSelectedKbIds] = useState([])
  const [retrievalFilters, setRetrievalFilters] = useState({ ...emptyFilters })
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [streaming, setStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 1280)
  useEffect(() => { const resize = () => { setNarrow(window.innerWidth <= 1279); setSidebarOpen(window.innerWidth >= 1280) }; window.addEventListener('resize', resize); return () => window.removeEventListener('resize', resize) }, [])
  const [kbMenuOpen, setKbMenuOpen] = useState(false)
  const [sourceDrawer, setSourceDrawer] = useState(null)
  const [error, setError] = useState('')
  const abortRef = useRef(null)
  const activeRequestRef = useRef(null)
  const [stopBusy, setStopBusy] = useState(false)
  const memoryLocks = useRef(new Set())
  const [memoryBusy, setMemoryBusy] = useState({})
  const sessionLocks = useRef(new Set())
  const bottomRef = useRef(null)
  const conversationRef = useRef(null)
  const { unseen, scrollToBottom } = useChatScroll(conversationRef, messages)
  const drawerRef = useRef(null)
  const historyRef = useRef(null)
  const [compact, setCompact] = useState(window.innerWidth <= 819)
  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 819)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  useEffect(() => {
    if (!compact || !sidebarOpen) return
    const previous = document.activeElement
    const panel = historyRef.current
    panel.querySelector('button')?.focus()
    const keydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); setSidebarOpen(false) }
      if (event.key !== 'Tab') return
      const items = [...panel.querySelectorAll('button:not(:disabled),input,summary')].filter(item => item.getClientRects().length)
      const index = items.indexOf(document.activeElement)
      if (index < 0 || (event.shiftKey && index === 0) || (!event.shiftKey && index === items.length - 1)) {
        event.preventDefault()
        items[event.shiftKey ? items.length - 1 : 0]?.focus()
      }
    }
    panel.addEventListener('keydown', keydown)
    return () => { panel.removeEventListener('keydown', keydown); if (previous?.isConnected) previous.focus() }
  }, [compact, sidebarOpen])
  useEffect(() => {
    if (!sourceDrawer) return
    const previous = document.activeElement
    const drawer = drawerRef.current
    drawer.querySelector('button')?.focus()
    function keydown(event) {
      if (event.key === 'Escape') { event.preventDefault(); setSourceDrawer(null) }
      if (event.key !== 'Tab' || !narrow) return
      const items = [...drawer.querySelectorAll('button:not(:disabled),a[href]')]
      const index = items.indexOf(document.activeElement)
      if (index < 0 || (event.shiftKey && index === 0) || (!event.shiftKey && index === items.length - 1)) {
        event.preventDefault()
        items[event.shiftKey ? items.length - 1 : 0]?.focus()
      }
    }
    drawer.addEventListener('keydown', keydown)
    return () => { drawer.removeEventListener('keydown', keydown); if (previous?.isConnected) previous.focus() }
  }, [sourceDrawer, narrow])
  /** @param {import("../api/generated/chat-source").ChatSource} source */
  function openSource(source) {
    const documentId = String(source.document_id || '').replace(/^doc_/, '')
    if (!/^\d+$/.test(documentId)) return
    const params = new URLSearchParams({ document: documentId })
    if (source.page) params.set('page', String(source.page))
    if (source.content_sha256) params.set('sha256', source.content_sha256)
    if (source.chunk_content) params.set('highlight', source.chunk_content.slice(0, 500))
    navigate(`/workspace?${params.toString()}`)
    setSourceDrawer(null)
  }

  const chooseSession = useCallback(async (session) => {
    if (abortRef.current) return
    const selection = ++selectionRef.current
    setSwitching(true)
    setError('')
    try {
      const history = await endpoints.sessionMessages(session.id)
      if (selection !== selectionRef.current) return
      setConversation({ session, messages: (history || []).map((message, index) => {
        let sources = message.sources || []
        try { if (message.sourcesJson) sources = JSON.parse(message.sourcesJson) } catch { /* old histories may not contain citations */ }
        return { ...message, status: message.status === 'completed' ? 'complete' : (message.status || 'complete'), sources, requestText: message.role === 'assistant' ? history.slice(0, index).findLast(item => item.role === 'user')?.content : undefined }
      }) })
      setSourceDrawer(null)
      if (window.innerWidth < 900) setSidebarOpen(false)
      scrollToBottom()
    } catch (requestError) {
      if (selection === selectionRef.current) setError(requestError.message)
    } finally { if (selection === selectionRef.current) setSwitching(false) }
  }, [scrollToBottom])

  useEffect(() => {
    let active = true
    Promise.allSettled([endpoints.sessions(), endpoints.knowledgeBases()])
      .then(([sessionResult, kbResult]) => {
        if (!active) return
        if (sessionResult.status === 'fulfilled') {
          const list = sessionResult.value || []; setSessions(list)
          const requested = new URLSearchParams(window.location.search).get('session')
          const match = list.find(item => String(item.id) === requested)
          if (match) void chooseSession(match)
        }
        if (kbResult.status === 'fulfilled') {
          const kbList = kbResult.value || []
          setKnowledgeBases(kbList)
          setSelectedKbIds(kbList.map((item) => String(item.id)))
        }
        const failure = [sessionResult, kbResult].find((result) => result.status === 'rejected')
        if (failure) setError(failure.reason?.message || t("部分数据加载失败，请刷新重试"))
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [chooseSession])

  useEffect(() => () => { selectionRef.current++; abortRef.current?.abort() }, [])


  function newChat() {
    if (abortRef.current) return
    selectionRef.current++
    setSwitching(false)
    setConversation({ session: null, messages: [] })
    setInput('')
    setSourceDrawer(null)
    if (window.innerWidth <= 819) setSidebarOpen(false)
    scrollToBottom()
  }

  async function ensureSession() {
    if (activeSession) return activeSession
    const created = await endpoints.createSession(t("新对话"))
    setConversation(current => ({ ...current, session: created }))
    setSessions((current) => [created, ...current])
    return created
  }

  async function sendMessage(event, retryText) {
    event?.preventDefault()
    const text = (retryText ?? input).trim()
    if (!text || abortRef.current || loading || switching) return
    const controller = new AbortController()
    const active = { controller, requestId: crypto.randomUUID(), sent: false, stopRequested: false, stopped: false, stopInFlight: false, terminal: false }
    activeRequestRef.current = active
    abortRef.current = controller
    setError('')
    setInput('')
    setStreaming(true)
    setStopBusy(false)
    const userMessage = { id: `u-${crypto.randomUUID()}`, role: 'user', content: text }
    const assistantId = `a-${crypto.randomUUID()}`
    scrollToBottom()
    const updateAssistant = (changes) => setMessages(current => current.map(message => message.id === assistantId ? { ...message, ...changes } : message))
    setMessages((current) => [...current, userMessage, { id: assistantId, role: 'assistant', content: '', sources: [], pending: [], status: 'streaming', requestText: text }])

    try {
      const session = await ensureSession()
      controller.signal.throwIfAborted()
      active.sent = true
      active.sessionId = String(session.id)
      const result = await streamChat({
        request_id: active.requestId,
        session_id: String(session.id),
        message: text,
        knowledge_base_ids: selectedKbIds,
        ...retrievalFilters,
      }, {
        signal: controller.signal,
        onEvent(name, data) {
          if (abortRef.current !== controller || controller.signal.aborted) return
          if (name === 'start' && data.request_id === active.requestId && String(data.session_id) === active.sessionId && Number.isSafeInteger(data.answer_generation) && data.answer_generation > 0) {
            active.generation = data.answer_generation
            if (active.stopRequested) void confirmStop(active)
          } else if (name === 'done') {
            active.terminal = true
          } else if (name === 'stopped') {
            active.stopped = true
            active.terminal = true
          } else if (name === 'meta') {
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, sources: data.sources || [], intent: data.intent } : message))
          } else if (name === 'token') {
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, content: message.content + (data.content || '') } : message))
          } else if (name === 'memory') {
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, pending: data.pending || [], memoryStatus: data.status } : message))

          }
        },
      })
      active.terminal = true
      setError(current => current === active.stopError ? '' : current)
      updateAssistant({ status: result?.status === 'stopped' ? 'stopped' : 'complete' })
      try {
        const refreshed = await endpoints.sessions()
        if (abortRef.current === controller) setSessions(refreshed || [])
      } catch { /* completed answers remain available if the history refresh fails */ }
    } catch (requestError) {
      const stopped = active.stopped
      if (stopped) setError(current => current === active.stopError ? '' : current)
      updateAssistant({ status: stopped ? 'stopped' : 'failed', error: stopped ? '' : requestError.message,
        errorCode: requestError.payload?.code || (requestError.status === 0 || requestError.name === 'AbortError' ? 'CLIENT_DISCONNECTED' : undefined) })
    } finally {
      if (abortRef.current === controller) {
        setStreaming(false)
        abortRef.current = null
        activeRequestRef.current = null
        setStopBusy(false)
      }
    }
  }

  async function confirmStop(active) {
    if (activeRequestRef.current !== active || active.terminal || active.stopInFlight || !active.generation) return
    active.stopInFlight = true
    try {
      const result = await endpoints.stopChat({ session_id: active.sessionId, request_id: active.requestId, answer_generation: active.generation })
      if (activeRequestRef.current !== active || active.terminal) return
      if (result?.status === 'stopped') {
        active.stopped = true
        active.controller.abort()
      } else if (result?.status !== 'completed') throw new Error(t('停止未确认，请重试；当前回答仍在生成'))
    } catch (requestError) {
      if (activeRequestRef.current === active && !active.terminal) {
        active.stopError = `${t('停止未确认，请重试；当前回答仍在生成')}：${requestError.message}`
        setError(active.stopError)
        active.stopRequested = false
      }
    } finally {
      active.stopInFlight = false
      if (activeRequestRef.current === active) setStopBusy(false)
    }
  }

  function stopGeneration() {
    const active = activeRequestRef.current
    if (!active || active.terminal || active.stopRequested) return
    active.stopRequested = true
    setStopBusy(true)
    if (!active.sent) { active.stopped = true; active.controller.abort() }
    else if (active.generation) void confirmStop(active)
  }

  async function removeSession(event, session) {
    event.stopPropagation()
    if (abortRef.current || switching || sessionLocks.current.has(session.id)) return
    sessionLocks.current.add(session.id)
    try {
      await endpoints.deleteSession(session.id)
      setSessions((current) => current.filter((item) => item.id !== session.id))
      setConversation(current => current.session?.id === session.id ? { session: null, messages: [] } : current)
    } catch (requestError) { setError(requestError.message) }
    finally { sessionLocks.current.delete(session.id) }
  }

  async function resolveMemory(messageId, memory, action) {
    if (memoryLocks.current.has(memory.temp_id)) return
    memoryLocks.current.add(memory.temp_id)
    setMemoryBusy(current => ({ ...current, [memory.temp_id]: true }))
    try {
      await endpoints.confirmMemory({ ...memory, action })
      setMessages((current) => current.map((message) => message.id === messageId ? {
        ...message, pending: message.pending.filter((item) => item.temp_id !== memory.temp_id),
      } : message))
    } catch (requestError) { setError(requestError.message) }
    finally {
      memoryLocks.current.delete(memory.temp_id)
      setMemoryBusy(current => ({ ...current, [memory.temp_id]: false }))
    }
  }

  const filteredSessions = sessions.filter(item => (item.title || '').toLowerCase().includes(historyQuery.toLowerCase()) && (!historyDate || dates.dateKey(item.updatedAt || item.createdAt) === historyDate) && (!historyRange || historyNow - (parseInstant(item.updatedAt || item.createdAt)?.getTime() ?? NaN) <= historyRange * 86400000))
  const displaySources = sourceDrawer || messages.findLast(message => message.sources?.length)?.sources || []
  async function rename(event) {
    event.preventDefault()
    if (renameLock.current) return
    renameLock.current = true; setRenameBusy(true)
    try {
      await endpoints.renameSession(renaming.id, renaming.title)
      setSessions(items => items.map(item => item.id === renaming.id ? { ...item, title: renaming.title } : item))
      setConversation(current => current.session?.id === renaming.id ? { ...current, session: { ...current.session, title: renaming.title } } : current)
      setRenaming(null)
    } catch (e) { setError(e.message) } finally { renameLock.current = false; setRenameBusy(false) }
  }
  const selectedLabel = useMemo(() => {
    if (!knowledgeBases.length) return t("暂无资料库")
    if (selectedKbIds.length === knowledgeBases.length) return t("全部资料库")
    if (!selectedKbIds.length) return t("不使用资料")
    return t("已选 {0} 个资料库", [selectedKbIds.length])
  }, [knowledgeBases, selectedKbIds])

  return (
    <div className={`chat-page reference-chat ${sidebarOpen ? '' : 'sidebar-collapsed'} ${!narrow ? 'with-sources' : ''}`}>
      {compact && sidebarOpen && <button className="history-scrim" aria-label={t('关闭会话栏')} tabIndex={-1} onClick={() => setSidebarOpen(false)} />}
      <aside ref={historyRef} className="chat-history" role={compact && sidebarOpen ? 'dialog' : undefined} aria-modal={compact && sidebarOpen ? true : undefined} inert={!sidebarOpen || (!!sourceDrawer && narrow)} aria-label={t("对话记录")}>
        <button className="history-close" onClick={() => setSidebarOpen(false)} aria-label={t('关闭会话栏')}><X size={16} />{t('关闭会话栏')}</button>
        <div className="history-head">
          <div><strong>{t("对话历史")}</strong></div>
          <button onClick={newChat} title={t("新对话")} aria-label={t("新对话")}><MessageSquarePlus size={16} /><span>{t('新建对话')}</span></button>
        </div>
<div className="history-filters"><label><Search size={16} /><input aria-label={t("搜索会话")} placeholder={t("搜索对话…")} value={historyQuery} onChange={e => setHistoryQuery(e.target.value)} /></label><div className="history-ranges">{[[0, '全部'], [7, '最近 7 天'], [30, '最近 30 天']].map(([days, label]) => <button key={days} aria-pressed={historyRange === days} onClick={() => { setHistoryRange(days); setHistoryDate('') }}>{t(label)}<small>{sessions.filter(item => !days || historyNow - (parseInstant(item.updatedAt || item.createdAt)?.getTime() ?? NaN) <= days * 86400000).length}</small></button>)}</div><details><summary>{t('按日期筛选会话')}</summary><input type="date" aria-label={t("按日期筛选会话")} value={historyDate} onChange={e => setHistoryDate(e.target.value)} /></details></div>
        <div className="history-list">
          {loading ? <LoadingState /> : filteredSessions.length ? filteredSessions.map((session) => (
            <div key={session.id} className={`history-item ${activeSession?.id === session.id ? 'active' : ''}`}>
              <button className="session-open" aria-label={t("打开对话：{0}", [session.title || '新对话'])} onClick={() => chooseSession(session)}><strong>{session.title || t("新对话")}</strong><small>{dates.date(session.updatedAt || session.createdAt)}</small></button>
              <button className="rename-session" disabled={streaming || switching} title={t("重命名会话")} aria-label={t("重命名会话：{0}", [session.title])} onClick={() => setRenaming({ id: session.id, title: session.title || t("新对话") })}>✎</button>
              <button className="delete-session" title={t("删除对话：{0}", [session.title || '新对话'])} aria-label={t("删除对话：{0}", [session.title || '新对话'])} onClick={(event) => removeSession(event, session)}><Trash2 size={15} /></button>
            </div>
          )) : <p className="history-empty">{t("还没有历史对话")}</p>}
        </div>
        <div className="history-foot"><Sparkles size={16} /><span>{t("从对话中积累学习记忆")}</span></div>
      </aside>

      <section className="chat-workspace" inert={(!!sourceDrawer && narrow) || (compact && sidebarOpen)}>
        <header className="chat-toolbar">
          <button className="collapse-history" onClick={() => setSidebarOpen((value) => !value)} title={t("切换会话栏")} aria-label={t("切换会话栏")} aria-expanded={sidebarOpen}>
            {sidebarOpen ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </button>
          <div className="chat-heading">
            <strong>{activeSession?.title || (workspace ? t('阅读工作台') : t("新的学习对话"))}</strong>
          </div>
          <div className="kb-selector">
            {renderTools && <div className="workspace-tool-menu"><button aria-expanded={toolsOpen} onClick={() => setToolsOpen(!toolsOpen)}><SlidersHorizontal size={16} />{t('工具')}</button>{toolsOpen && <div>{[['reader', '引用阅读'], ['debug', '检索调试'], ['branch', '分支对比']].map(([id, label]) => <button key={id} onClick={() => { setToolMode(id); setToolsOpen(false) }}>{t(label)}</button>)}</div>}</div>}
            <button aria-label={selectedLabel} aria-expanded={kbMenuOpen} onClick={() => setKbMenuOpen((value) => !value)}><BookOpen size={16} /><span>{selectedLabel}</span><ChevronDown size={15} /></button>
            {kbMenuOpen && (
              <div className="kb-menu">
                <div><strong>{t("检索范围")}</strong><button aria-label={t("关闭检索范围")} title={t("关闭检索范围")} onClick={() => setKbMenuOpen(false)}><X size={15} /></button></div>
                {knowledgeBases.length ? knowledgeBases.map((kb) => {
                  const id = String(kb.id)
                  const checked = selectedKbIds.includes(id)
                  return <label key={id}><input type="checkbox" checked={checked} onChange={() => { setSelectedKbIds((current) => checked ? current.filter((item) => item !== id) : [...current, id]); setRetrievalFilters({ ...emptyFilters }) }} /><span className="custom-check">{checked && <Check size={12} />}</span><span>{kb.name}</span></label>
                }) : <p>{t("请先在资料库页面上传学习资料。")}</p>}
              </div>
            )}
          </div>
        </header>

        <div ref={conversationRef} className="conversation" aria-busy={switching}>
          {switching && <p role="status">{t("正在切换对话…")}</p>}
          {!messages.length ? (
            <div className="chat-welcome">
              <p className="eyebrow">{t("开始新的学习对话")}</p>
              <h1>{t("今天想弄懂什么？")}</h1>
              <p>{t("直接提问，或从已上传的课件、笔记和报告中寻找答案。")}</p>
              <div className="prompt-grid">
                {[t("梳理这份资料的核心结构"), t("根据我的薄弱点安排复习"), t("对比两个概念的差异"), t("检查我的理解是否准确")].map((prompt, index) => (
                  <button key={prompt} onClick={() => setInput(prompt)}><span>0{index + 1}</span>{prompt}</button>
                ))}
              </div>
            </div>
          ) : messages.map((message) => (
            <article key={message.id} className={`message message-${message.role}`}>
              <div className="message-label">{message.role === 'user' ? <span className="message-avatar">{t('我')}</span> : <img src={logo} alt="Mneme" />}</div>
              <div className="message-body">
                {message.role === 'assistant' ? (
                  message.content ? <><div className="assistant-name">Mneme</div><Suspense fallback={<p style={{ whiteSpace: 'pre-wrap' }}>{message.content}</p>}><AnswerMarkdown>{message.content}</AnswerMarkdown></Suspense></> : message.status === 'streaming' ? <div className="thinking" role="status" aria-label={t("正在生成回答")}><span /><span /><span /></div> : <p>{message.status === 'stopped' ? t("已停止生成") : t("未生成回答")}</p>
                ) : <p>{message.content}</p>}
                {message.role === 'assistant' && <div className="message-actions">
                  {message.status === 'failed' && <p role="alert">{answerFailure(message)}{message.content ? ` · ${t('已保留部分回答')}` : ''}</p>}
                  {message.content && <button onClick={async () => { try { await navigator.clipboard.writeText(message.content + (message.sources?.length ? '\n\n' + message.sources.map((source, index) => `[${index + 1}] ${source.document_name || source.document_id} · ${source.page || t("全文")}\n${source.chunk_content || ''}`).join('\n\n') : '')) } catch { setError(t("复制失败，请手动选择文本复制")) } }}>{t("复制回答")}</button>}
                  {message.status === 'stopped' && message.content && <span role="status">{t("已停止 · 保留部分回答")}</span>}
                  {['failed', 'stopped'].includes(message.status) && message.requestText && <button disabled={streaming || switching} onClick={() => sendMessage(null, message.requestText)}>{t("重试")}</button>}
                </div>}
                {!!message.sources?.length && (
                  <button className="source-trigger" onClick={() => setSourceDrawer(message.sources)}><Quote size={15} />{t("查看 ")}{message.sources.length}{t(" 条资料依据")}</button>
                )}
                {message.memoryStatus === 'queued' && <p className="muted" role="status">{t('回答已保存，候选记忆正在后台保存。')} <Link to="/tasks">{t('查看记忆任务')}</Link> · <Link to="/memory">{t('前往学习记忆确认')}</Link></p>}
                {!!message.pending?.length && <div className="memory-confirmations">{message.pending.map((memory) => (
                  <div key={memory.temp_id} aria-busy={!!memoryBusy[memory.temp_id]}><Sparkles size={16} /><span><small>{t("是否记住")}</small>{memory.content}</span><button disabled={!!memoryBusy[memory.temp_id]} onClick={() => resolveMemory(message.id, memory, 'confirm')} title={t("确认")} aria-label={t("确认记忆")}><Check size={15} /></button><button disabled={!!memoryBusy[memory.temp_id]} onClick={() => resolveMemory(message.id, memory, 'dismiss')} title={t("忽略")} aria-label={t("忽略记忆")}><X size={15} /></button></div>
                ))}</div>}
              </div>
            </article>
          ))}
          {error && <div className="chat-error" role="alert">{error}</div>}
          <div ref={bottomRef} />
        </div>

        {unseen && <button className="new-content" onClick={scrollToBottom}>{t("有新内容 · 返回底部")}</button>}
        <form className="composer" onSubmit={sendMessage} aria-busy={switching}>
          <div className="composer-tools"><RetrievalFilters kbIds={selectedKbIds} value={retrievalFilters} onChange={setRetrievalFilters} /><button type="button" onClick={() => navigate('/knowledge')}><FileText size={14} />{t('导入资料')}</button><button type="button" onClick={() => setKbMenuOpen(!kbMenuOpen)}><Quote size={14} />{t('引用检索')}</button><button type="button" onClick={() => setSourceDrawer(displaySources)}><BookOpen size={14} />{t('引用与原文')}{displaySources.length ? ` · ${displaySources.length}` : ''}</button></div>
          <textarea aria-label={t("向忆知提问...")} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); sendMessage() } }} placeholder={t("向忆知提问...")} rows={1} />
          <span className="composer-context"><FileText size={14} />{selectedLabel}</span>
          {streaming ? <button type="button" className="stop-send" disabled={stopBusy} onClick={stopGeneration} title={t("停止生成")} aria-label={t("停止生成")}><CircleStop size={19} /></button> : <button className="send-message" disabled={loading || switching || !input.trim()} title={t("发送")} aria-label={t("发送")}><ArrowUp size={20} /></button>}
        </form>
      </section>

      {(!narrow || sourceDrawer) && <aside ref={drawerRef} className="source-drawer" role={narrow ? "dialog" : "complementary"} aria-modal={narrow ? true : undefined} aria-labelledby="source-title">
        <header><div><strong id="source-title">{t("引用与原文")}</strong></div>{narrow ? <button title={t("关闭资料依据")} aria-label={t("关闭资料依据")} onClick={() => setSourceDrawer(null)}><X size={18} /></button> : <small>{t('{0} 条引用', [displaySources.length])}</small>}</header>
        {!displaySources.length && <div className="source-empty"><Quote size={28} /><h3>{t('资料依据')}</h3><p>{t('选择资料库并提问后，回答引用的原文会显示在这里。')}</p></div>}
        <div>{displaySources.map((source, index) => <article key={`${source.document_id || source.document_name}-${index}`}>
          <div><span>{index + 1}</span><strong>{source.document_name}</strong></div>
          <small>{source.page ? t("第 {0} 页", [source.page]) : t("全文")}{source.section ? ` · ${source.section}` : ''}</small>
          <blockquote className="source-excerpt">{source.chunk_content}</blockquote><div className="action-row"><button className="source-open" onClick={() => openSource(source)} disabled={!source.document_id}>{t("打开原文定位")}</button><button onClick={async () => { try { await navigator.clipboard.writeText(`${source.document_name || source.document_id} · ${source.page || ''}\n${source.chunk_content || ''}`) } catch { setError(t('复制失败，请手动选择文本复制')) } }}>{t('复制引用')}</button></div><details><summary>{t('来源信息')}</summary>
          {!!Object.keys(source.retrieval_ranks || {}).length && <p className="source-signals">{t("召回路径：")}{Object.entries(source.retrieval_ranks).map(([channel, rank]) => `${channel.startsWith('dense:') ? t("向量") : t("词法")} #${rank}`).join(' · ')}{Number.isFinite(source.score) ? t(" · 排序信号 {0}（非可信概率）", [fmt.decimal(source.score, 3)]) : ''}</p>}
          {source.indexed_at && <small>{t("索引时间：")}{dates.dateTime(source.indexed_at)}{t(" · 解析器 ")}{source.parser_version || t("未知")}</small>}
          {source.content_sha256 && <small title={source.content_sha256}>{t("文件版本 SHA-256：")}{source.content_sha256.slice(0, 16)}…</small>}
          <p className="muted">{t("资料依据需结合原文核验；排序信号不代表事实正确。")}</p></details>
        </article>)}</div>
      </aside>}
      {renderTools && <Modal open={!!toolMode} title={t('工作台工具')} onClose={() => setToolMode(null)}>{toolMode && renderTools(toolMode)}</Modal>}
      <Modal open={!!renaming} title={t("重命名会话")} onClose={() => setRenaming(null)} busy={renameBusy}>{renaming && <form className="form-stack" onSubmit={rename}><label>{t("会话标题")}<input required maxLength={120} value={renaming.title} onChange={e => setRenaming({ ...renaming, title: e.target.value })} /></label>{error && <p role="alert">{error}</p>}<button className="primary-button" disabled={renameBusy || !renaming.title.trim()}>{t("保存标题")}</button></form>}</Modal>
    </div>
  )
}
