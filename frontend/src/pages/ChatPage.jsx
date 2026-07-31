import {
  ArrowUp, BookOpen, Check, ChevronDown, CircleStop, FileText, MessageSquarePlus,
  PanelLeftClose, PanelLeftOpen, Quote, Sparkles, Trash2, X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { endpoints, streamChat } from '../api/client'
import LoadingState from '../components/LoadingState'
import '../styles/chat.css'

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(new Date(value))
}

export default function ChatPage() {
  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [knowledgeBases, setKnowledgeBases] = useState([])
  const [selectedKbIds, setSelectedKbIds] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [streaming, setStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 760)
  const [kbMenuOpen, setKbMenuOpen] = useState(false)
  const [sourceDrawer, setSourceDrawer] = useState(null)
  const [error, setError] = useState('')
  const abortRef = useRef(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    Promise.allSettled([endpoints.sessions(), endpoints.knowledgeBases()])
      .then(([sessionResult, kbResult]) => {
        if (sessionResult.status === 'fulfilled') setSessions(sessionResult.value || [])
        if (kbResult.status === 'fulfilled') {
          const kbList = kbResult.value || []
          setKnowledgeBases(kbList)
          setSelectedKbIds(kbList.map((item) => String(item.id)))
        }
        const failure = [sessionResult, kbResult].find((result) => result.status === 'rejected')
        if (failure) setError(failure.reason?.message || '部分数据加载失败，请刷新重试')
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])
  useEffect(() => () => abortRef.current?.abort(), [])

  async function chooseSession(session) {
    if (streaming) return
    setActiveSession(session)
    setError('')
    try {
      const history = await endpoints.sessionMessages(session.id)
      setMessages((history || []).map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        createdAt: message.createdAt,
      })))
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  function newChat() {
    if (streaming) return
    setActiveSession(null)
    setMessages([])
    setInput('')
    setSourceDrawer(null)
  }

  async function ensureSession() {
    if (activeSession) return activeSession
    const created = await endpoints.createSession('新对话')
    setActiveSession(created)
    setSessions((current) => [created, ...current])
    return created
  }

  async function sendMessage(event) {
    event?.preventDefault()
    const text = input.trim()
    if (!text || streaming) return
    setError('')
    setInput('')
    setStreaming(true)
    const userMessage = { id: `u-${Date.now()}`, role: 'user', content: text }
    const assistantId = `a-${Date.now()}`
    setMessages((current) => [...current, userMessage, { id: assistantId, role: 'assistant', content: '', sources: [], pending: [] }])

    try {
      const session = await ensureSession()
      const controller = new AbortController()
      abortRef.current = controller
      await streamChat({
        request_id: crypto.randomUUID(),
        session_id: String(session.id),
        message: text,
        knowledge_base_ids: selectedKbIds,
      }, {
        signal: controller.signal,
        onEvent(name, data) {
          if (name === 'meta') {
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, sources: data.sources || [], intent: data.intent } : message))
          } else if (name === 'token') {
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, content: message.content + (data.content || '') } : message))
          } else if (name === 'memory') {
            setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, pending: data.pending || [] } : message))
          } else if (name === 'error') {
            setError(data.message || '回答生成失败')
          }
        },
      })
      const refreshed = await endpoints.sessions()
      setSessions(refreshed || [])
    } catch (requestError) {
      if (requestError.name !== 'AbortError') setError(requestError.message)
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  async function removeSession(event, session) {
    event.stopPropagation()
    await endpoints.deleteSession(session.id)
    setSessions((current) => current.filter((item) => item.id !== session.id))
    if (activeSession?.id === session.id) newChat()
  }

  async function resolveMemory(messageId, memory, action) {
    await endpoints.confirmMemory({ ...memory, action })
    setMessages((current) => current.map((message) => message.id === messageId ? {
      ...message,
      pending: message.pending.filter((item) => item.temp_id !== memory.temp_id),
    } : message))
  }

  const selectedLabel = useMemo(() => {
    if (!knowledgeBases.length) return '暂无资料库'
    if (selectedKbIds.length === knowledgeBases.length) return '全部资料库'
    if (!selectedKbIds.length) return '不使用资料'
    return `已选 ${selectedKbIds.length} 个资料库`
  }, [knowledgeBases, selectedKbIds])

  return (
    <div className={`chat-page ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      <aside className="chat-history">
        <div className="history-head">
          <div><span>学习空间</span><strong>对话记录</strong></div>
          <button onClick={newChat} title="新对话"><MessageSquarePlus size={19} /></button>
        </div>
        <div className="history-list">
          {loading ? <LoadingState /> : sessions.length ? sessions.map((session) => (
            <button key={session.id} className={activeSession?.id === session.id ? 'active' : ''} onClick={() => chooseSession(session)}>
              <span><strong>{session.title || '新对话'}</strong><small>{formatTime(session.updatedAt || session.createdAt)}</small></span>
              <Trash2 className="delete-session" size={15} onClick={(event) => removeSession(event, session)} />
            </button>
          )) : <p className="history-empty">还没有历史对话</p>}
        </div>
        <div className="history-foot"><Sparkles size={16} /><span>忆知会从对话中形成学习画像</span></div>
      </aside>

      <section className="chat-workspace">
        <header className="chat-toolbar">
          <button className="collapse-history" onClick={() => setSidebarOpen((value) => !value)} title="切换会话栏">
            {sidebarOpen ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </button>
          <div className="chat-heading">
            <span className="live-dot" />
            <strong>{activeSession?.title || '新的学习对话'}</strong>
          </div>
          <div className="kb-selector">
            <button onClick={() => setKbMenuOpen((value) => !value)}><BookOpen size={16} /><span>{selectedLabel}</span><ChevronDown size={15} /></button>
            {kbMenuOpen && (
              <div className="kb-menu">
                <div><strong>检索范围</strong><button onClick={() => setKbMenuOpen(false)}><X size={15} /></button></div>
                {knowledgeBases.length ? knowledgeBases.map((kb) => {
                  const id = String(kb.id)
                  const checked = selectedKbIds.includes(id)
                  return <label key={id}><input type="checkbox" checked={checked} onChange={() => setSelectedKbIds((current) => checked ? current.filter((item) => item !== id) : [...current, id])} /><span className="custom-check">{checked && <Check size={12} />}</span><span>{kb.name}</span></label>
                }) : <p>请先在资料库页面上传学习资料。</p>}
              </div>
            )}
          </div>
        </header>

        <div className="conversation">
          {!messages.length ? (
            <div className="chat-welcome">
              <p className="eyebrow">开始新的学习对话</p>
              <h1>今天想弄懂什么？</h1>
              <p>直接提问，或从已上传的课件、笔记和报告中寻找答案。</p>
              <div className="prompt-grid">
                {['梳理这份资料的核心结构', '根据我的薄弱点安排复习', '对比两个概念的差异', '检查我的理解是否准确'].map((prompt, index) => (
                  <button key={prompt} onClick={() => setInput(prompt)}><span>0{index + 1}</span>{prompt}</button>
                ))}
              </div>
            </div>
          ) : messages.map((message) => (
            <article key={message.id} className={`message message-${message.role}`}>
              <div className="message-label">{message.role === 'user' ? '你' : '忆知'}</div>
              <div className="message-body">
                {message.role === 'assistant' ? (
                  message.content ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown> : <div className="thinking"><span /><span /><span /></div>
                ) : <p>{message.content}</p>}
                {!!message.sources?.length && (
                  <button className="source-trigger" onClick={() => setSourceDrawer(message.sources)}><Quote size={15} />查看 {message.sources.length} 条资料依据</button>
                )}
                {!!message.pending?.length && <div className="memory-confirmations">{message.pending.map((memory) => (
                  <div key={memory.temp_id}><Sparkles size={16} /><span><small>是否记住</small>{memory.content}</span><button onClick={() => resolveMemory(message.id, memory, 'confirm')} title="确认"><Check size={15} /></button><button onClick={() => resolveMemory(message.id, memory, 'dismiss')} title="忽略"><X size={15} /></button></div>
                ))}</div>}
              </div>
            </article>
          ))}
          {error && <div className="chat-error">{error}</div>}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={sendMessage}>
          <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage() } }} placeholder="向忆知提问..." rows={1} />
          <span className="composer-context"><FileText size={14} />{selectedLabel}</span>
          {streaming ? <button type="button" className="stop-send" onClick={() => abortRef.current?.abort()} title="停止生成"><CircleStop size={19} /></button> : <button className="send-message" disabled={!input.trim()} title="发送"><ArrowUp size={20} /></button>}
        </form>
      </section>

      {sourceDrawer && <aside className="source-drawer">
        <header><div><span>引用依据</span><strong>资料依据</strong></div><button onClick={() => setSourceDrawer(null)}><X size={18} /></button></header>
        <div>{sourceDrawer.map((source, index) => <article key={`${source.document_name}-${index}`}><div><span>{index + 1}</span><strong>{source.document_name}</strong></div><small>{source.page ? `第 ${source.page} 页` : '全文'}{source.section ? ` · ${source.section}` : ''}</small><p>{source.chunk_content}</p></article>)}</div>
      </aside>}
    </div>
  )
}
