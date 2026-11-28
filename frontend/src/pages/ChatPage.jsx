import useIndependentRead from '../hooks/useIndependentRead'
import { validBases, validSessions } from '../api/collectionValidation'
import { useAuth } from '../state/AuthContext'
import { t, useI18n } from '../i18n'
import {
  BookOpen, Check, ChevronDown,
  PanelLeftClose, PanelLeftOpen, Quote, SlidersHorizontal, Sparkles, X,
} from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { endpoints, streamChat } from '../api/client'
import { FeedbackBlock, Modal } from '../components/ui'
import ChatHistoryPanel from '../features/chat/ChatHistoryPanel'
import ChatComposer from '../features/chat/ChatComposer'
import ChatSourceDrawer from '../features/chat/ChatSourceDrawer'
import normalizeChatHistory from '../features/chat/normalizeChatHistory'
import { emptyFilters } from '../components/RetrievalFilters'
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
    INVALID_CHAT_EVENT: '回答流格式异常，请重试',
  }
  return message.error || t(Object.hasOwn(labels, message.errorCode) ? labels[message.errorCode] : '回答未完成，请重试')
}

export default function ChatPage(props) {
  const session = useAuth()?.session
  return <ChatView key={session?.userId || session?.username || 'anonymous'} {...props} />
}

function ChatView({ renderTools, workspace = false }) {
  useI18n();
  const navigate = useNavigate()
  const location = useLocation()
  const [toolsOpen, setToolsOpen] = useState(false)
  const toolsTrigger = useRef(null)
  const [toolMode, setToolMode] = useState(() => workspace && new URLSearchParams(window.location.search).has('document') ? 'reader' : null)
  useEffect(() => { if (workspace && new URLSearchParams(location.search).has('document')) setToolMode('reader') }, [workspace, location.search])
  const [renaming, setRenaming] = useState(null)
  const [renameBusy, setRenameBusy] = useState(false)
  const renameLock = useRef(false)
  const [narrow, setNarrow] = useState(window.innerWidth <= 1279)
  const sessionRead = useIndependentRead(endpoints.sessions, validSessions)
  const kbRead = useIndependentRead(endpoints.knowledgeBases, validBases)
  const knowledgeBases = kbRead.data || []
  const setSessions = sessionRead.commit
  const sessionUnavailable = sessionRead.data === null || sessionRead.error || sessionRead.loading
  const kbUnavailable = kbRead.data === null || kbRead.error || kbRead.loading
  const initialSelection = useRef(new URLSearchParams(window.location.search).get('session'))
  const [requestedPending, setRequestedPending] = useState(!!initialSelection.current)
  const kbInitialized = useRef(false)
  const [conversation, setConversation] = useState({ session: null, messages: [] })
  const { session: activeSession, messages } = conversation
  const setMessages = (update) => setConversation(current => ({ ...current, messages: typeof update === 'function' ? update(current.messages) : update }))
  const [switching, setSwitching] = useState(false)
  const [historyFailure, setHistoryFailure] = useState(null)
  const selectionRef = useRef(0)
  const [selectedKbIds, setSelectedKbIds] = useState([])
  const [retrievalFilters, setRetrievalFilters] = useState({ ...emptyFilters })
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 1280)
  useEffect(() => { const resize = () => { setNarrow(window.innerWidth <= 1279); setSidebarOpen(window.innerWidth >= 1280) }; window.addEventListener('resize', resize); return () => window.removeEventListener('resize', resize) }, [])
  const [kbMenuOpen, setKbMenuOpen] = useState(false)
  const [sourceDrawer, setSourceDrawer] = useState(null)
  const [error, setError] = useState('')
  const [deletionTask, setDeletionTask] = useState(null)
  const [deletingSessions, setDeletingSessions] = useState([])
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const abortRef = useRef(null)
  const activeRequestRef = useRef(null)
  const [stopBusy, setStopBusy] = useState(false)
  const memoryLocks = useRef(new Set())
  const [memoryBusy, setMemoryBusy] = useState({})
  const sessionLocks = useRef(new Set())
  const bottomRef = useRef(null)
  const conversationRef = useRef(null)
  const { unseen, scrollToBottom } = useChatScroll(conversationRef, messages)
  const [compact, setCompact] = useState(window.innerWidth <= 819)
  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 819)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  const closeSources = useCallback(() => setSourceDrawer(null), [])

  const chooseSession = useCallback(async (session) => {
    if (abortRef.current || sessionLocks.current.has(session.id)) return
    const selection = ++selectionRef.current
    setSwitching(true)
    setHistoryFailure(null)
    setError('')
    try {
      const history = await endpoints.sessionMessages(session.id)
      if (selection !== selectionRef.current) return
      setConversation({ session, messages: normalizeChatHistory(history, session.id) })
      setSourceDrawer(null)
      if (window.innerWidth < 900) setSidebarOpen(false)
      scrollToBottom()
    } catch {
      if (selection === selectionRef.current) setHistoryFailure(session)
    } finally { if (selection === selectionRef.current) setSwitching(false) }
  }, [scrollToBottom])

  useEffect(() => {
    if (sessionRead.data === null || !initialSelection.current) return
    const requested = initialSelection.current
    initialSelection.current = null
    const match = sessionRead.data.find(item => String(item.id) === requested)
    if (match) void chooseSession(match)
    setRequestedPending(false)
  }, [sessionRead.data, chooseSession])
  useEffect(() => {
    if (kbRead.data === null) return
    const ids = kbRead.data.map(item => String(item.id))
    const initialized = kbInitialized.current
    setSelectedKbIds(current => initialized ? current.filter(id => ids.includes(id)) : ids)
    kbInitialized.current = true
  }, [kbRead.data])

  useEffect(() => () => { selectionRef.current++; abortRef.current?.abort() }, [])


  function newChat() {
    if (abortRef.current) return
    selectionRef.current++
    initialSelection.current = null
    setRequestedPending(false)
    setSwitching(false)
    setHistoryFailure(null)
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
    if (!text || abortRef.current || kbUnavailable || requestedPending || switching || historyFailure) return
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
      void sessionRead.refresh()
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
    if (abortRef.current || switching || sessionUnavailable || sessionLocks.current.has(session.id)) return
    sessionLocks.current.add(session.id)
    setDeletingSessions(current => [...current, session.id])
    setError('')
    setDeletionTask(null)
    try {
      const receipt = await endpoints.deleteSession(session.id)
      if (!mounted.current) return
      if (receipt?.accepted !== true || typeof receipt.task_id !== 'string' || !/^task_[a-zA-Z0-9_]+$/.test(receipt.task_id)
        || !['pending', 'processing', 'retry', 'failed', 'completed'].includes(receipt.status))
        throw new Error(t('删除结果未确认，请刷新会话与任务中心核对后再操作。'))
      setSessions((current) => current.filter((item) => item.id !== session.id))
      setConversation(current => current.session?.id === session.id ? { session: null, messages: [] } : current)
      setDeletionTask(receipt)
    } catch (requestError) { if (mounted.current) setError(requestError.message) }
    finally {
      sessionLocks.current.delete(session.id)
      if (mounted.current) setDeletingSessions(current => current.filter(id => id !== session.id))
    }
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

  const displaySources = sourceDrawer || messages.findLast(message => message.sources?.length)?.sources || []
  async function rename(event) {
    event.preventDefault()
    if (renameLock.current || sessionUnavailable) return
    renameLock.current = true; setRenameBusy(true)
    try {
      await endpoints.renameSession(renaming.id, renaming.title)
      setSessions(items => items.map(item => item.id === renaming.id ? { ...item, title: renaming.title } : item))
      setConversation(current => current.session?.id === renaming.id ? { ...current, session: { ...current.session, title: renaming.title } } : current)
      setRenaming(null)
    } catch (e) { setError(e.message) } finally { renameLock.current = false; setRenameBusy(false) }
  }
  const selectedLabel = (() => {
    if (kbRead.error) return t('资料库暂不可用')
    if (kbRead.loading || kbRead.data === null) return t('资料库加载中…')
    if (!knowledgeBases.length) return t("暂无资料库")
    if (selectedKbIds.length === knowledgeBases.length) return t("全部资料库")
    if (!selectedKbIds.length) return t("不使用资料")
    return t("已选 {0} 个资料库", [selectedKbIds.length])
  })()

  return (
    <div className={`chat-page reference-chat ${sidebarOpen ? '' : 'sidebar-collapsed'} ${!narrow ? 'with-sources' : ''}`}>
      {compact && sidebarOpen && <button className="history-scrim" aria-label={t('关闭会话栏')} tabIndex={-1} onClick={() => setSidebarOpen(false)} />}
      <ChatHistoryPanel read={sessionRead} unavailable={sessionUnavailable} activeSessionId={activeSession?.id}
        streaming={streaming} switching={switching} deletingSessions={deletingSessions}
        open={sidebarOpen} compact={compact} sourceModalOpen={!!sourceDrawer && narrow} setOpen={setSidebarOpen}
        onNew={newChat} onChoose={chooseSession} onRename={setRenaming} onDelete={removeSession} />

      <section className="chat-workspace" inert={(!!sourceDrawer && narrow) || (compact && sidebarOpen)}>
        <header className="chat-toolbar">
          <button className="collapse-history" onClick={() => setSidebarOpen((value) => !value)} title={t("切换会话栏")} aria-label={t("切换会话栏")} aria-expanded={sidebarOpen}>
            {sidebarOpen ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </button>
          <div className="chat-heading">
            <strong>{activeSession?.title || (workspace ? t('阅读工作台') : t("新的学习对话"))}</strong>
          </div>
          <div className="kb-selector">
            {renderTools && <div className="workspace-tool-menu"><button ref={toolsTrigger} aria-expanded={toolsOpen} onClick={() => setToolsOpen(!toolsOpen)}><SlidersHorizontal size={16} />{t('工具')}</button>{toolsOpen && <div>{[['reader', '引用阅读'], ['debug', '检索调试'], ['branch', '分支对比']].map(([id, label]) => <button key={id} onClick={() => { toolsTrigger.current?.focus(); setToolMode(id); setToolsOpen(false) }}>{t(label)}</button>)}</div>}</div>}
            <button aria-label={selectedLabel} aria-expanded={kbMenuOpen} onClick={() => setKbMenuOpen((value) => !value)}><BookOpen size={16} /><span>{selectedLabel}</span><ChevronDown size={15} /></button>
            {kbMenuOpen && (
              <div className="kb-menu">
                <div><strong>{t("检索范围")}</strong><button aria-label={t("关闭检索范围")} title={t("关闭检索范围")} onClick={() => setKbMenuOpen(false)}><X size={15} /></button></div>
                {knowledgeBases.length ? knowledgeBases.map((kb) => {
                  const id = String(kb.id)
                  const checked = selectedKbIds.includes(id)
                  return <label key={id}><input type="checkbox" checked={checked} disabled={kbUnavailable || streaming} onChange={() => { setSelectedKbIds((current) => checked ? current.filter((item) => item !== id) : [...current, id]); setRetrievalFilters({ ...emptyFilters }) }} /><span className="custom-check">{checked && <Check size={12} />}</span><span>{kb.name}</span></label>
                }) : !kbUnavailable && <p>{t("请先在资料库页面上传学习资料。")}</p>}
                <button disabled={kbRead.loading || streaming} onClick={kbRead.refresh}>{t('刷新资料库')}</button>
              </div>
            )}
          </div>
        </header>

        <div className="chat-read-feedback" role="region" aria-label={t('对话资料库读取')} aria-busy={kbRead.loading}>
          {kbRead.loading && <p role="status">{t('资料库加载中…')}</p>}
          <FeedbackBlock error={kbRead.error ? t('资料库加载失败。已有记录可能不是最新状态，请重试。') : ''} onRetry={kbRead.loading ? undefined : kbRead.refresh} />
        </div>
        <div ref={conversationRef} className="conversation" aria-busy={switching}>
          {switching && <p role="status">{t("正在切换对话…")}</p>}
          {historyFailure && <FeedbackBlock error={t('历史消息加载失败，已保留当前回答和草稿。请重试读取或选择新对话。')}
            onRetry={switching || sessionUnavailable ? undefined : () => chooseSession(historyFailure)} />}
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
                  {['failed', 'stopped'].includes(message.status) && message.requestText && <button disabled={streaming || switching || sessionUnavailable} onClick={() => sendMessage(null, message.requestText)}>{t("重试")}</button>}
                </div>}
                {!!message.sources?.length && (
                  <button className="source-trigger" onClick={() => setSourceDrawer(message.sources)}><Quote size={15} />{t("查看 ")}{message.sources.length}{t(" 条资料依据")}</button>
                )}
                {message.memoryStatus === 'queued' && <p className="muted" role="status">{t('回答已保存，记忆正在后台处理。')} <Link to="/tasks">{t('查看记忆任务')}</Link> · <Link to="/memory">{t('前往学习记忆确认')}</Link></p>}
                {!!message.pending?.length && <div className="memory-confirmations">{message.pending.map((memory) => (
                  <div key={memory.temp_id} aria-busy={!!memoryBusy[memory.temp_id]}><Sparkles size={16} /><span><small>{t("是否记住")}</small>{memory.content}</span><button disabled={!!memoryBusy[memory.temp_id]} onClick={() => resolveMemory(message.id, memory, 'confirm')} title={t("确认")} aria-label={t("确认记忆")}><Check size={15} /></button><button disabled={!!memoryBusy[memory.temp_id]} onClick={() => resolveMemory(message.id, memory, 'dismiss')} title={t("忽略")} aria-label={t("忽略记忆")}><X size={15} /></button></div>
                ))}</div>}
              </div>
            </article>
          ))}
          {error && <div className="chat-error" role="alert">{error}</div>}
          {deletionTask && <div className="hint-panel" role="status">{t(deletionTask.status === 'completed' ? '会话清理已完成。' : '会话删除已受理，最终清理结果请在任务中心查看。')} <Link to="/tasks">{t('查看清理任务')}</Link></div>}
          <div ref={bottomRef} />
        </div>

        {unseen && <button className="new-content" onClick={scrollToBottom}>{t("有新内容 · 返回底部")}</button>}
        <ChatComposer
          draft={input}
          onDraftChange={setInput}
          onSend={sendMessage}
          switching={switching}
          canSend={!kbUnavailable && !requestedPending && !switching && !historyFailure && !!input.trim()}
          streaming={streaming}
          stopBusy={stopBusy}
          onStop={stopGeneration}
          knowledgeBasesUnavailable={kbUnavailable}
          selectedKbIds={selectedKbIds}
          retrievalFilters={retrievalFilters}
          onRetrievalFiltersChange={setRetrievalFilters}
          selectedLabel={selectedLabel}
          sourceCount={displaySources.length}
          onOpenKnowledge={() => navigate('/knowledge')}
          onToggleKnowledgeMenu={() => setKbMenuOpen(value => !value)}
          onOpenSources={() => setSourceDrawer(displaySources)}
        />
      </section>

      <ChatSourceDrawer sources={displaySources} open={sourceDrawer} narrow={narrow}
        onClose={closeSources} onError={setError} />
      {renderTools && <Modal open={!!toolMode} title={t('工作台工具')} onClose={() => setToolMode(null)}>{toolMode && renderTools(toolMode)}</Modal>}
      <Modal open={!!renaming} title={t("重命名会话")} onClose={() => setRenaming(null)} busy={renameBusy}>{renaming && <form className="form-stack" onSubmit={rename}><label>{t("会话标题")}<input required maxLength={120} value={renaming.title} onChange={e => setRenaming({ ...renaming, title: e.target.value })} /></label>{error && <p role="alert">{error}</p>}<button className="primary-button" disabled={renameBusy || !renaming.title.trim()}>{t("保存标题")}</button></form>}</Modal>
    </div>
  )
}
