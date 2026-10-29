import { t, useI18n } from '../i18n'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, CheckCircle2, X } from 'lucide-react'

const dialogs = []
let originalOverflow = '', originalInert = false

export function PageHeader({ eyebrow, title, description, children }) {
  useI18n();
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{t(eyebrow)}</p>}<h1>{title}</h1>{description && <p>{t(description)}</p>}</div>{children && <div className="header-actions">{children}</div>}</header>
}

export function FeedbackBlock({ error, message, onRetry }) {
  useI18n();
  if (!error && !message) return null
  return <div className={`feedback-block ${error ? 'is-error' : 'is-success'}`} role={error ? 'alert' : 'status'}>
    {error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}<span>{error || message}</span>{onRetry && <button onClick={onRetry}>{t("重试 / Retry")}</button>}
  </div>
}

export function StatusPill({ tone = 'neutral', children }) {
  useI18n();
  return <span className={`status-pill tone-${tone}`}>{children}</span>
}

export function Modal({ open = true, title, onClose, busy = false, drawer = false, children }) {
  useI18n();
  const ref = useRef(null)
  const closeRef = useRef(onClose)
  const busyRef = useRef(busy)
  const titleId = useId()
  useEffect(() => { closeRef.current = onClose; busyRef.current = busy }, [onClose, busy])
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    const root = document.getElementById('root')
    if (!dialogs.length) { originalInert = root?.inert || false; originalOverflow = document.body.style.overflow }
    const entry = { panel: ref.current, previous }
    dialogs.push(entry)
    dialogs.forEach(item => { item.panel.inert = item !== entry })
    if (root) root.inert = true
    document.body.style.overflow = 'hidden'
    const controls = () => [...ref.current.querySelectorAll('a[href],button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')].filter(item => !item.hidden)
    ;(controls()[0] || ref.current).focus()
    function keydown(event) {
      if (dialogs.at(-1) !== entry) return
      if (event.key === 'Escape' && !busyRef.current) { event.preventDefault(); closeRef.current() }
      if (event.key !== 'Tab') return
      const items = controls()
      const index = items.indexOf(document.activeElement)
      if (!items.length || index < 0 || (!event.shiftKey && index === items.length - 1) || (event.shiftKey && index === 0)) {
        event.preventDefault()
        ;(items[event.shiftKey ? items.length - 1 : 0] || ref.current).focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      const wasTop = dialogs.at(-1) === entry
      dialogs.splice(dialogs.indexOf(entry), 1)
      const top = dialogs.at(-1)
      if (top) top.panel.inert = false
      else {
        if (root) root.inert = originalInert
        document.body.style.overflow = originalOverflow
      }
      document.removeEventListener('keydown', keydown)
      if (wasTop && previous?.isConnected && !previous.closest('[inert]')) previous.focus()
      else if (wasTop && top) top.panel.focus()
    }
  }, [open])
  if (!open) return null
  return createPortal(<div className={`modal-overlay ${drawer ? 'as-drawer' : ''}`} onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <section ref={ref} className="modal-panel" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header><h2 id={titleId}>{title}</h2><button className="icon-button" disabled={busy} onClick={onClose} aria-label={t("关闭 / Close")}><X size={20} /></button></header>{children}
    </section>
  </div>, document.body)
}

export function SideDrawer(props) {
  useI18n(); return <Modal {...props} drawer /> }

export function DangerZone({ title, description, action, confirmText, onConfirm, busy = false }) {
  useI18n();
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  async function confirm() {
    if (running || typed !== confirmText) return
    setRunning(true); setError('')
    try { await onConfirm(); setOpen(false); setTyped('') }
    catch (failure) { setError(failure.message) }
    finally { setRunning(false) }
  }
  return <section className="danger-zone"><div><h2>{title}</h2><p>{t(description)}</p></div><button className="danger-button" disabled={busy} onClick={() => { setTyped(''); setError(''); setOpen(true) }}>{t(action)}</button>
    <Modal open={open} onClose={() => setOpen(false)} title={title} busy={running}><p>{t(description)}</p><p>{t("请输入 / Type ")}<strong>{confirmText}</strong></p><input aria-label={t("确认文字 / Confirmation")} value={typed} onChange={event => setTyped(event.target.value)} autoComplete="off" /><FeedbackBlock error={error} /><footer><button disabled={running} onClick={() => setOpen(false)}>{t("取消 / Cancel")}</button><button className="danger-button" disabled={typed !== confirmText || running} onClick={confirm}>{running ? t("处理中 / Working…") : action}</button></footer></Modal>
  </section>
}
