import { t, useI18n } from '../i18n'
import { Activity, ArchiveRestore, BrainCircuit, CalendarDays, ClipboardCheck, Library, ListTodo, LogOut, Menu, MessageSquareText, Moon, PanelsTopLeft, Settings, ShieldCheck, Sun, X, UserRound, FileText } from 'lucide-react'
import { Suspense, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { endpoints } from '../api/client'
import logo from '../assets/mneme-logo.svg'
import BrandLockup from './BrandLockup'
import '../styles/app-shell.css'
import { useAuth } from '../state/AuthContext'
import { usePreferences } from '../state/PreferencesContext'

const navItems = [
  { to: '/chat', label: '对话', icon: MessageSquareText, group: 'learning' },
  { to: '/knowledge', label: '知识库', icon: Library, group: 'learning' },
  { to: '/memory', label: '学习记忆', icon: BrainCircuit, group: 'learning' },
  { to: '/review', label: '复习计划', icon: CalendarDays, group: 'learning' },
  { to: '/quiz', label: '知识测验', icon: ClipboardCheck, group: 'learning' },
  { to: '/analytics', label: '学习分析', icon: Activity, group: 'learning' },
  { to: '/workspace', label: '阅读工作台', icon: PanelsTopLeft, group: 'workspace' },
  { to: '/tasks', label: '任务中心', icon: ListTodo, group: 'workspace' },
  { to: '/profile', label: '个人资料', icon: UserRound, group: 'account' },
  { to: '/legal/terms', label: '法律与协议', icon: FileText, group: 'account' },
  { to: '/recovery', label: '备份恢复', icon: ArchiveRestore, group: 'account' },
  { to: '/privacy', label: '数据与隐私', icon: ShieldCheck, group: 'account' },
  { to: '/settings', label: '设置', icon: Settings, group: 'account' },
  { to: '/operations', label: '管理员运维', icon: Activity, group: 'admin', admin: true },
]
const navGroups = [
  { id: 'learning', label: '学习空间' },
  { id: 'workspace', label: '工作空间' },
  { id: 'account', label: '账户与设置' },
  { id: 'admin', label: '管理' },
]

export default function AppShell() {
  useI18n();
  const [open, setOpen] = useState(false)
  const { session, logout, isAdmin } = useAuth()
  const { preferences, save } = usePreferences()
  const [themeError, setThemeError] = useState('')
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const activeItem = navItems.find(item => item.to === pathname || (item.to === '/legal/terms' && pathname.startsWith('/legal/')))
  const activeGroup = navGroups.find(group => group.id === activeItem?.group)
  const groups = navGroups.map(group => ({ ...group, items: navItems.filter(item => item.group === group.id && (!item.admin || isAdmin)) })).filter(group => group.items.length)
  const mainRef = useRef(null)
  const navRef = useRef(null)
  const toggleRef = useRef(null)
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 1100px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(max-width: 1100px)')
    const update = () => { setMobile(query.matches); setOpen(false) }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  useEffect(() => { mainRef.current?.focus({ preventScroll: true }) }, [pathname])
  useLayoutEffect(() => {
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
        <BrandLockup className="brand-mark" onClick={() => setOpen(false)} />
        <nav aria-label={t("主要导航")}>
          {groups.map(group => (
            <section className="nav-group" key={group.id} aria-labelledby={`nav-group-${group.id}`}>
              <h2 id={`nav-group-${group.id}`}>{t(group.label)}</h2>
              {group.items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} onClick={() => setOpen(false)} className={({ isActive }) => isActive ? 'active' : ''}>
                <Icon size={19} strokeWidth={1.8} /><span>{t(label)}</span>
              </NavLink>)}
            </section>
          ))}
        </nav>
        <div className="nav-note"><img src={logo} alt="" /><p>{t('知识是时间的礼物，')}<br />{t('而记忆是你的翅膀。')}</p><small>— Mneme</small></div>
      </aside>
      {!['/chat','/workspace'].includes(pathname) && <div className="reference-topbar"><span>{t(activeGroup?.label || 'Mneme')}</span><span>/</span><strong>{t(activeItem?.label || 'Mneme')}</strong></div>}
      <div className="shell-account">
          <button className="icon-button" aria-label={t('切换主题')} onClick={async () => { try { await save({ ...preferences, theme: document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark' }); setThemeError('') } catch (e) { setThemeError(e.message) } }}>{preferences.theme === 'dark' ? <Moon size={19} /> : <Sun size={19} />}</button>
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
      </div>
      {themeError && <div className="shell-error" role="alert">{themeError}</div>}
      {open && <button className="nav-scrim" onClick={closeNav} aria-label={t("关闭导航遮罩")} tabIndex={-1} />}
      <main ref={mainRef} id="main-content" className="route-stage" tabIndex={-1} aria-label={t("主要内容")} inert={mobile && open}><Suspense fallback={<p className="loading-state" role="status">{t("加载中...")}</p>}><Outlet /></Suspense></main>
    </div>
  )
}
