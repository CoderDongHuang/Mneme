import { t, useI18n } from '../i18n'
import { ArrowRight, BookOpenCheck, Brain, DatabaseZap, Eye, EyeOff } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../state/AuthContext'
import '../styles/auth.css'
import '../styles/theme.css'
import logo from '../assets/mneme-logo.svg'
import { endpoints } from '../api/client'
import { usePreferences } from '../state/PreferencesContext'

export default function AuthPage() {
  useI18n();
  const { session, login, register } = useAuth()
  const { preferences, save: savePreferences } = usePreferences()
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
  const lock = useRef(false)
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update); window.addEventListener('offline', update)
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update) }
  }, [])

  if (session) return <Navigate to={location.state?.from || '/chat'} replace />

  async function submit(event) {
    event.preventDefault()
    if (lock.current) return
    lock.current = true
    setError('')
    setBusy(true)
    try {
      if (mode === 'reset') {
        if (!resetRequested) {
          await endpoints.requestPasswordReset({ username: resetForm.username, email: resetForm.email })
          setResetRequested(true)
          setNotice(t("如果账号信息匹配，验证码已发送到绑定邮箱"))
        } else {
          await endpoints.confirmPasswordReset({ token: resetForm.token, newPassword: resetForm.newPassword })
          setNotice(t("密码已重置，请使用新密码登录")); setMode('login'); setResetRequested(false)
        }
      } else {
        await (mode === 'login' ? login({ ...form, remember }) : register(form))
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-story">
        <div className="auth-wordmark"><img src={logo} alt={t("忆知")} />{t(" 忆知")}</div>
        <div className="auth-thesis">
          <p className="eyebrow">{t("个人学习智能系统")}</p>
          <h1>{t("知识会遗忘，")}<br />{t("理解可以延续。")}</h1>
          <p>{t("忆知将你的资料、问题与学习轨迹组织成一个持续生长的认知系统。")}</p>
          <div className="auth-orbit" aria-hidden="true"><span>{t("阅读")}</span><i /><span>{t("理解")}</span><i /><span>{t("记住")}</span></div>
        </div>
        <div className="auth-capabilities">
          <div><DatabaseZap size={19} /><span>{t("资料可追溯")}</span></div>
          <div><Brain size={19} /><span>{t("跨会话记忆")}</span></div>
          <div><BookOpenCheck size={19} /><span>{t("主动学习建议")}</span></div>
        </div>
      </section>

      <section className="auth-panel">
        <label className="auth-language">Language / 语言<select aria-label="Language / 语言" value={preferences.language} onChange={event => savePreferences({ ...preferences, language: event.target.value }).catch(failure => setError(failure.message))}><option value="zh-CN">简体中文</option><option value="en">English</option></select></label>
        <form className="auth-form" onSubmit={submit}>
          <div className="auth-form-heading">
            <p>{mode === 'login' ? t("欢迎回来") : mode === 'register' ? t("建立学习档案") : t("找回访问权限")}</p>
            <h2>{mode === 'login' ? t("继续你的学习轨迹") : mode === 'register' ? t("从第一次提问开始") : t("通过绑定邮箱重置密码")}</h2>
          </div>
          <div className="auth-tabs" role="tablist" aria-label={t("账号操作")}>
            <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>{t("登录")}</button>
            <button type="button" role="tab" aria-selected={mode === 'register'} className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>{t("注册")}</button>
          </div>
          {mode !== 'reset' && <label>
            <span>{t("用户名")}</span>
            <input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} autoComplete="username" minLength={3} maxLength={50} required placeholder={t("输入用户名")} />
          </label>}
          {mode !== 'reset' && <label>
            <span>{t("密码")}</span>
            <div className="password-field">
              <input type={visible ? 'text' : 'password'} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required placeholder={t("至少 8 个字符")} />
              <button type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? t("隐藏密码") : t("显示密码")}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button>
            </div>
          </label>}
          {mode === 'reset' && <>
            <label><span>{t("用户名")}</span><input value={resetForm.username} onChange={(e)=>setResetForm({...resetForm,username:e.target.value})} required placeholder={t("输入用户名")} /></label>
            <label><span>{t("绑定邮箱")}</span><input type="email" value={resetForm.email} onChange={(e)=>setResetForm({...resetForm,email:e.target.value})} required placeholder={t("输入已绑定邮箱")} /></label>
            {resetRequested && <><label><span>{t("邮箱验证码")}</span><input value={resetForm.token} onChange={(e)=>setResetForm({...resetForm,token:e.target.value})} required placeholder={t("输入 15 分钟内收到的验证码")} /></label><label><span>{t("新密码")}</span><input type="password" minLength="8" value={resetForm.newPassword} onChange={(e)=>setResetForm({...resetForm,newPassword:e.target.value})} required placeholder={t("至少 8 个字符")} /></label></>}
          </>}
          {mode === 'login' && <div className="auth-options"><label><input type="checkbox" checked={remember} onChange={(e)=>setRemember(e.target.checked)} /><span>{t("记住我")}</span></label><button type="button" onClick={()=>{setMode('reset');setError('');setNotice('')}}>{t("忘记密码")}</button></div>}
          {mode === 'reset' && <button className="back-login" type="button" onClick={()=>{setMode('login');setResetRequested(false)}}>{t("返回登录")}</button>}
          {!online && <p className="auth-network" role="status">{t("网络已断开。输入已保留，连接恢复后可重新提交。")}</p>}
          {error && <div className="form-error" role="alert">{error}<p>{t("请检查网络和服务状态后重试，表单内容已保留。")}</p></div>}
          {notice && <div className="auth-notice" role="status" aria-live="polite">{notice}</div>}
          <button className="auth-submit" type="submit" disabled={busy}>
            <span>{busy ? t("请稍候") : mode === 'login' ? t("进入忆知") : mode === 'register' ? t("创建账号") : resetRequested ? t("确认重置密码") : t("发送验证码")}</span>
            <ArrowRight size={19} />
          </button>
          <div className="auth-proof"><span>{t("本地优先")}</span><i /><span>{t("引用可追溯")}</span><i /><span>{t("记忆可管理")}</span></div>
          <div className="auth-legal"><Link to="/legal/privacy">{t("隐私政策")}</Link><Link to="/legal/terms">{t("服务条款")}</Link></div>
          <p className="auth-demo">{t("离线演示仅提供原文摘录，不进行真实模型推理。真实问答需在登录后配置模型服务。")}</p>
        </form>
      </section>
    </div>
  )
}
