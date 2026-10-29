import { t, useI18n } from '../i18n'
import { Activity, ArchiveRestore, BrainCircuit, CalendarDays, ClipboardCheck, Library, ListTodo, LogOut, Menu, MessageSquareText, PanelsTopLeft, Settings, ShieldCheck, X } from 'lucide-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { endpoints } from '../api/client'
import logo from '../assets/mneme-logo.svg'
import { useAuth } from '../state/AuthContext'

const navItems = [
  { to: '/chat', label: '对话', icon: MessageSquareText },
  { to: '/knowledge', label: '资料库', icon: Library },
  { to: '/memory', label: '学习记忆', icon: BrainCircuit },
  { to: '/review', label: '复习计划', icon: CalendarDays },
  { to: '/quiz', label: '知识测验', icon: ClipboardCheck },
  { to: '/workspace', label: '阅读工作台', icon: PanelsTopLeft },
  { to: '/analytics', label: '学习分析', icon: Activity },
  { to: '/tasks', label: '任务中心', icon: ListTodo },
  { to: '/recovery', label: '备份恢复', icon: ArchiveRestore },
  { to: '/privacy', label: '数据与隐私', icon: ShieldCheck },
  { to: '/operations', label: '管理员运维', icon: Activity, admin: true },
  { to: '/settings', label: '服务配置', icon: Settings },
]

export default function AppShell() {
  useI18n();
  const [open, setOpen] = useState(false)
  const { session, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const mainRef = useRef(null)
  const navRef = useRef(null)
  const toggleRef = useRef(null)
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 760px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(max-width: 760px)')
    const update = () => { setMobile(query.matches); setOpen(false) }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  useEffect(() => { mainRef.current?.focus({ preventScroll: true }) }, [pathname])
  useEffect(() => {
    if (!open || !mobile) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const controls = () => [toggleRef.current, ...navRef.current.querySelectorAll('a,button:not(:disabled)')]
    controls()[1]?.focus()
    function keydown(event) {
      if (event.key === 'Escape') { setOpen(false); toggleRef.current?.focus(); event.preventDefault() }
      if (event.key !== 'Tab') return
      const items = controls()
      const current = items.indexOf(document.activeElement)
      if (current < 0 || (!event.shiftKey && current === items.length - 1) || (event.shiftKey && current === 0)) {
        event.preventDefault()
        items[event.shiftKey ? items.length - 1 : 0]?.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', keydown) }
  }, [open, mobile])

  function closeNav() { setOpen(false); toggleRef.current?.focus() }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content" onClick={() => mainRef.current?.focus()}>{t("跳转到主要内容")}</a>
      <button ref={toggleRef} className="mobile-nav-toggle" onClick={() => open ? closeNav() : setOpen(true)} aria-label={open ? t("关闭导航") : t("打开导航")} aria-expanded={open} aria-controls="global-navigation">
        {open ? <X size={20} /> : <Menu size={20} />}
      </button>
      <aside ref={navRef} id="global-navigation" className={`global-nav ${open ? 'is-open' : ''}`} inert={mobile && !open}>
        <NavLink to="/chat" className="brand-mark" onClick={() => setOpen(false)} aria-label={t("忆知首页")}>
          <img className="brand-glyph" src={logo} alt={t("忆知")} />
          <span className="brand-name">{t("忆知")}</span>
        </NavLink>
        <nav aria-label={t("主要导航")}>
          {navItems.filter(item => !item.admin || isAdmin).map(({ to, label, icon: Icon }, index) => (
            <div key={to}>{(index === 0 || to === '/tasks') && <p className="nav-group-label">{index === 0 ? t("学习空间") : t("管理")}</p>}<NavLink to={to} onClick={() => setOpen(false)} className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon size={19} strokeWidth={1.8} />
              <span>{t(label)}</span>
            </NavLink></div>
          ))}
        </nav>
        <div className="nav-profile">
          <button className="profile-entry" onClick={() => { setOpen(false); navigate('/profile') }} title={t("打开用户中心")} aria-label={t("打开用户中心")}>
            {session?.hasAvatar ? <img className="avatar avatar-image" src={`${endpoints.avatarUrl()}?v=${session.avatarVersion || 0}`} alt={t("用户头像")} /> : <span className="avatar">{(session?.nickname || session?.username)?.slice(0, 1) || t("忆")}</span>}
            <span className="profile-copy">
              <strong>{session?.nickname || session?.username}</strong>
              <small>{t("学习者")}</small>
            </span>
          </button>
          <button className="logout-button" onClick={logout} title={t("退出登录")} aria-label={t("退出登录")}><LogOut size={17} /></button>
        </div>
      </aside>
      {open && <button className="nav-scrim" onClick={closeNav} aria-label={t("关闭导航遮罩")} tabIndex={-1} />}
      <main ref={mainRef} id="main-content" className="route-stage" tabIndex={-1} aria-label={t("主要内容")} inert={mobile && open}><Suspense fallback={<p className="loading-state" role="status">{t("加载中...")}</p>}><Outlet /></Suspense></main>
    </div>
  )
}
