import { BrainCircuit, Library, LogOut, Menu, MessageSquareText, PanelsTopLeft, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { endpoints } from '../api/client'
import logo from '../assets/mneme-logo.svg'
import { useAuth } from '../state/AuthContext'

const navItems = [
  { to: '/chat', label: '对话', icon: MessageSquareText },
  { to: '/knowledge', label: '资料库', icon: Library },
  { to: '/memory', label: '学习画像', icon: BrainCircuit },
  { to: '/workspace', label: '学习工作台', icon: PanelsTopLeft },
]

export default function AppShell() {
  const [open, setOpen] = useState(false)
  const { session, logout } = useAuth()
  const navigate = useNavigate()

  function moveBackdrop(event) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 14
    const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 10
    event.currentTarget.style.setProperty('--backdrop-x', `${x}px`)
    event.currentTarget.style.setProperty('--backdrop-y', `${y}px`)
  }

  return (
    <div className="app-shell" onPointerMove={moveBackdrop} onPointerLeave={(event) => {
      event.currentTarget.style.setProperty('--backdrop-x', '0px')
      event.currentTarget.style.setProperty('--backdrop-y', '0px')
    }}>
      <button className="mobile-nav-toggle" onClick={() => setOpen((value) => !value)} aria-label="打开导航">
        {open ? <X size={20} /> : <Menu size={20} />}
      </button>
      <aside className={`global-nav ${open ? 'is-open' : ''}`}>
        <NavLink to="/chat" className="brand-mark" onClick={() => setOpen(false)} aria-label="忆知首页">
          <img className="brand-glyph" src={logo} alt="忆知" />
          <span className="brand-name">忆知</span>
        </NavLink>
        <nav>
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setOpen(false)} className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon size={19} strokeWidth={1.8} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="nav-profile">
          <button className="profile-entry" onClick={() => navigate('/profile')} title="打开用户中心">
            {session?.hasAvatar ? <img className="avatar avatar-image" src={`${endpoints.avatarUrl()}?v=${session.avatarVersion || 0}`} alt="用户头像" /> : <span className="avatar">{(session?.nickname || session?.username)?.slice(0, 1) || '忆'}</span>}
            <span className="profile-copy">
              <strong>{session?.nickname || session?.username}</strong>
              <small>学习者</small>
            </span>
          </button>
          <button className="logout-button" onClick={logout} title="退出登录" aria-label="退出登录"><LogOut size={17} /></button>
        </div>
      </aside>
      {open && <button className="nav-scrim" onClick={() => setOpen(false)} aria-label="关闭导航" />}
      <main className="route-stage"><Outlet /></main>
    </div>
  )
}
