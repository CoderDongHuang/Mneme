import { ArrowRight, BookOpenCheck, Brain, DatabaseZap, Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../state/AuthContext'
import '../styles/auth.css'
import logo from '../assets/mneme-logo.svg'
import { endpoints } from '../api/client'

export default function AuthPage() {
  const { session, login, register } = useAuth()
  const location = useLocation()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ username: '', password: '' })
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [remember, setRemember] = useState(true)
  const [resetForm, setResetForm] = useState({ username: '', email: '', token: '', newPassword: '' })
  const [resetRequested, setResetRequested] = useState(false)
  const [notice, setNotice] = useState('')

  if (session) return <Navigate to={location.state?.from || '/chat'} replace />

  async function submit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'reset') {
        if (!resetRequested) {
          await endpoints.requestPasswordReset({ username: resetForm.username, email: resetForm.email })
          setResetRequested(true)
          setNotice('如果账号信息匹配，验证码已发送到绑定邮箱')
        } else {
          await endpoints.confirmPasswordReset({ token: resetForm.token, newPassword: resetForm.newPassword })
          setNotice('密码已重置，请使用新密码登录'); setMode('login'); setResetRequested(false)
        }
      } else {
        await (mode === 'login' ? login({ ...form, remember }) : register(form))
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-story">
        <div className="auth-wordmark"><img src={logo} alt="忆知" /> 忆知</div>
        <div className="auth-thesis">
          <p className="eyebrow">个人学习智能系统</p>
          <h1>知识会遗忘，<br />理解可以延续。</h1>
          <p>忆知将你的资料、问题与学习轨迹组织成一个持续生长的认知系统。</p>
        </div>
        <div className="auth-capabilities">
          <div><DatabaseZap size={19} /><span>资料可追溯</span></div>
          <div><Brain size={19} /><span>跨会话记忆</span></div>
          <div><BookOpenCheck size={19} /><span>主动学习建议</span></div>
        </div>
        <div className="auth-index">让资料成为持续生长的理解</div>
        <div className="auth-photo-credit">图书馆学习空间</div>
      </section>

      <section className="auth-panel">
        <form className="auth-form" onSubmit={submit}>
          <div className="auth-form-heading">
            <p>{mode === 'login' ? '欢迎回来' : mode === 'register' ? '建立学习档案' : '找回访问权限'}</p>
            <h2>{mode === 'login' ? '继续你的学习轨迹' : mode === 'register' ? '从第一次提问开始' : '通过绑定邮箱重置密码'}</h2>
          </div>
          <div className="auth-tabs" role="tablist">
            <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>登录</button>
            <button type="button" className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>注册</button>
          </div>
          {mode !== 'reset' && <label>
            <span>用户名</span>
            <input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} autoComplete="username" minLength={3} maxLength={50} required placeholder="输入用户名" />
          </label>}
          {mode !== 'reset' && <label>
            <span>密码</span>
            <div className="password-field">
              <input type={visible ? 'text' : 'password'} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required placeholder="至少 8 个字符" />
              <button type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? '隐藏密码' : '显示密码'}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button>
            </div>
          </label>}
          {mode === 'reset' && <>
            <label><span>用户名</span><input value={resetForm.username} onChange={(e)=>setResetForm({...resetForm,username:e.target.value})} required placeholder="输入用户名" /></label>
            <label><span>绑定邮箱</span><input type="email" value={resetForm.email} onChange={(e)=>setResetForm({...resetForm,email:e.target.value})} required placeholder="输入已绑定邮箱" /></label>
            {resetRequested && <><label><span>邮箱验证码</span><input value={resetForm.token} onChange={(e)=>setResetForm({...resetForm,token:e.target.value})} required placeholder="输入 15 分钟内收到的验证码" /></label><label><span>新密码</span><input type="password" minLength="8" value={resetForm.newPassword} onChange={(e)=>setResetForm({...resetForm,newPassword:e.target.value})} required placeholder="至少 8 个字符" /></label></>}
          </>}
          {mode === 'login' && <div className="auth-options"><label><input type="checkbox" checked={remember} onChange={(e)=>setRemember(e.target.checked)} /><span>记住我</span></label><button type="button" onClick={()=>{setMode('reset');setError('');setNotice('')}}>忘记密码</button></div>}
          {mode === 'reset' && <button className="back-login" type="button" onClick={()=>{setMode('login');setResetRequested(false)}}>返回登录</button>}
          {error && <div className="form-error" role="alert">{error}</div>}
          {notice && <div className="auth-notice">{notice}</div>}
          <button className="auth-submit" disabled={busy}>
            <span>{busy ? '请稍候' : mode === 'login' ? '进入忆知' : mode === 'register' ? '创建账号' : resetRequested ? '确认重置密码' : '发送验证码'}</span>
            <ArrowRight size={19} />
          </button>
          <div className="auth-proof"><span>本地优先</span><i /><span>引用可追溯</span><i /><span>记忆可管理</span></div>
          <div className="auth-legal"><Link to="/legal/privacy">隐私政策</Link><Link to="/legal/terms">服务条款</Link></div>
        </form>
      </section>
    </div>
  )
}
