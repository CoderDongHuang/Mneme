import { formatDateTime } from '../utils/dates'
import { t, useI18n } from '../i18n'
import { Camera, KeyRound, Mail, Save, UserRound, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'
import LoadingState from '../components/LoadingState'
import { useAuth } from '../state/AuthContext'
import { usePreferences } from '../state/PreferencesContext'
import { Link } from 'react-router-dom'
import { FeedbackBlock, PageHeader } from '../components/ui'
import '../styles/profile.css'

export default function ProfilePage() {
  useI18n();
  const { updateSession, logout } = useAuth()
  const { preferences, save: savePreferences, error: preferenceError } = usePreferences()
  const [localeForm, setLocaleForm] = useState(preferences)
  const [tab, setTab] = useState('basic')
  const [sessions, setSessions] = useState([])
  useEffect(() => { setLocaleForm(preferences) }, [preferences])
  const fileInput = useRef(null)
  const [profile, setProfile] = useState(null)
  const [savedEmail, setSavedEmail] = useState('')
  const [emailToken, setEmailToken] = useState('')
  const [emailSent, setEmailSent] = useState(false)
  const [passwords, setPasswords] = useState({ currentPassword: '', newPassword: '', confirm: '' })
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const actionLock = useRef(false)
  const [avatarVersion, setAvatarVersion] = useState(0)
  useEffect(() => { let active = true; endpoints.authSessions().then(items => { if (active) setSessions(items || []) }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [])

  function acceptProfile(value) {
    setProfile(value); setSavedEmail(value.email || ''); setEmailToken(''); setEmailSent(false)
  }
  useEffect(() => { let active = true; endpoints.profile().then(value => { if (active) acceptProfile(value) }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [])
  async function run(action, success) {
    if (actionLock.current) return
    actionLock.current = true
    setBusy(true); setError(''); setNotice('')
    try { await action(); setNotice(success) } catch (e) { setError(e.message) } finally { actionLock.current = false; setBusy(false) }
  }
  async function saveProfile(event) {
    event.preventDefault()
    await run(async () => { const data = await endpoints.updateProfile({ nickname: profile.nickname, email: profile.email }); acceptProfile(data); updateSession(data) }, t("个人资料已保存"))
  }
  async function requestEmail() {
    await run(async () => { await endpoints.requestEmailVerification(savedEmail); setEmailSent(true) }, t('验证邮件已提交至邮件服务器，请检查收件箱。验证码 15 分钟内有效。'))
  }
  async function confirmEmail(event) {
    event.preventDefault()
    await run(async () => { const data = await endpoints.confirmEmailVerification(emailToken.trim()); acceptProfile(data); updateSession(data) }, t('邮箱验证成功，现在可以用于找回密码。'))
  }
  async function upload(event) {
    const file = event.target.files?.[0]
    if (!file) return
    await run(async () => { const data = await endpoints.uploadAvatar(file); acceptProfile(data); const version = Date.now(); setAvatarVersion(version); updateSession({ ...data, avatarVersion: version }) }, t("头像已更新"))
    event.target.value = ''
  }
  async function changePassword(event) {
    event.preventDefault()
    if (passwords.newPassword !== passwords.confirm) { setError(t("两次输入的新密码不一致")); return }
    await run(async () => { await endpoints.changePassword({ currentPassword: passwords.currentPassword, newPassword: passwords.newPassword }); logout() }, t("密码已修改，请重新登录"))
  }

  if (!profile) return error ? <div className="standard-page"><FeedbackBlock error={error} onRetry={() => { setError(''); endpoints.profile().then(acceptProfile).catch(e => setError(e.message)) }} /></div> : <LoadingState label={t("正在读取用户资料")} />
  const emailChanged = (profile.email || '').trim().toLowerCase() !== savedEmail.trim().toLowerCase()
  return <div className="standard-page account-page profile-page">
    <PageHeader title={t('个人资料')} description={t('管理个人信息、账户安全和偏好设置')} />
    <FeedbackBlock error={error} message={notice} />
    <div className="account-columns">
      <div className="account-main">
        <nav className="segmented-tabs" aria-label={t('个人资料分组')}><button aria-pressed={tab === 'basic'} onClick={() => setTab('basic')}>{t('基本资料')}</button><button aria-pressed={tab === 'security'} onClick={() => setTab('security')}>{t('账户安全')}</button></nav>
        <div hidden={tab !== 'basic'} className="profile-basics">
      <section className="identity-panel">
        <button className="avatar-editor" onClick={() => fileInput.current?.click()} disabled={busy} title={t("更换头像")}>
          {profile.hasAvatar ? <img src={`${endpoints.avatarUrl()}?v=${avatarVersion}`} alt={t("当前头像")} /> : <UserRound size={54} />}
          <span><Camera size={16} />{t("更换头像")}</span>
        </button>
        <input ref={fileInput} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={upload} />
        <div><strong>{profile.nickname || profile.username}</strong><small>@{profile.username}</small><p>{t("资料、偏好与账户安全")}</p></div>
      </section>
      <form className="profile-form" onSubmit={saveProfile}>
        <header><UserRound size={20}/><div><h2>{t("基本资料")}</h2><p>{t("设置对外显示的昵称和绑定邮箱")}</p></div></header>
        <label><span>{t("昵称")}</span><input disabled={busy} value={profile.nickname ?? ''} maxLength="50" onChange={(e) => setProfile({...profile,nickname:e.target.value})} placeholder={t("输入昵称")} /></label>
        <label><span>{t("绑定邮箱")}</span><div className="profile-input"><Mail size={17}/><input disabled={busy} type="email" maxLength={120} value={profile.email ?? ''} onChange={(e) => setProfile({...profile,email:e.target.value})} placeholder={t("用于找回密码")} /></div></label>
        <button disabled={busy}><Save size={17}/>{t("保存资料")}</button>
      </form>
      <section className="profile-form email-verification" aria-labelledby="email-verification-title">
        <h2 id="email-verification-title">{t('邮箱验证')}</h2>
        <p role="status">{emailChanged ? t('邮箱有未保存的修改，请先保存资料。') : profile.emailVerified ? t('当前邮箱已验证，可用于找回密码。') : t('当前邮箱尚未验证，不能用于找回密码。')}</p>
        {!emailChanged && !profile.emailVerified && savedEmail && <>
          <button type="button" disabled={busy} onClick={requestEmail}>{t(emailSent ? '重新发送验证码' : '发送邮箱验证码')}</button>
          <p className="muted">{t('请复制邮件中的完整验证码；重新发送需间隔 60 秒，新验证码会使旧验证码失效。')}</p>
          <form onSubmit={confirmEmail}>
            <label>{t('邮箱验证码')}<input disabled={busy} value={emailToken} onChange={event => setEmailToken(event.target.value)} autoComplete="one-time-code" spellCheck={false} minLength={64} maxLength={64} pattern="[0-9a-f]{64}" required /></label>
            <button disabled={busy || emailToken.trim().length !== 64}>{t('验证邮箱')}</button>
          </form>
        </>}
      </section>
        </div>
        <div hidden={tab !== 'security'} className="profile-security">
      <form className="profile-form" onSubmit={changePassword}>
        <header><KeyRound size={20}/><div><h2>{t("修改密码")}</h2><p>{t("修改后请使用新密码再次登录")}</p></div></header>
        <label><span>{t("当前密码")}</span><input type="password" value={passwords.currentPassword} onChange={(e)=>setPasswords({...passwords,currentPassword:e.target.value})} required /></label>
        <label><span>{t("新密码")}</span><input type="password" minLength="8" value={passwords.newPassword} onChange={(e)=>setPasswords({...passwords,newPassword:e.target.value})} required /></label>
        <label><span>{t("确认新密码")}</span><input type="password" minLength="8" value={passwords.confirm} onChange={(e)=>setPasswords({...passwords,confirm:e.target.value})} required /></label>
        <button disabled={busy}><KeyRound size={17}/>{t("确认修改")}</button>
      </form>
      <section className="profile-form"><h2>{t("登录会话")}</h2><p className="muted">{t("撤销会话后，对应设备的登录凭证立即失效；撤销当前会话需要重新登录。")}</p><ul className="plain-list">{sessions.map(item => <li key={item.session_id}><strong>{item.remembered ? t("长期登录") : t("普通登录")}</strong><small>{t("最近活动：")}{formatDateTime(item.last_seen_at, localeForm.language, localeForm.timezone)}</small><button disabled={busy} onClick={() => run(async () => { await endpoints.revokeAuthSession(item.session_id); setSessions(await endpoints.authSessions()) }, t("会话已撤销"))}>{t("撤销会话")}</button></li>)}</ul>{!sessions.length && <p>{t("暂无活动会话。")}</p>}</section>
        </div>
      </div>
      <aside className="account-aside">
      <form className="profile-form" onSubmit={event => { event.preventDefault(); run(async () => { await savePreferences(localeForm) }, t("偏好已保存")) }}>
        <h2>{t("语言与偏好")}</h2><FeedbackBlock error={preferenceError} />
        <label>{t("界面语言")}<select aria-label={t("界面语言")} value={localeForm.language} onChange={e => setLocaleForm({ ...localeForm, language: e.target.value })}><option value="zh-CN">{t("简体中文")}</option><option value="en">English</option></select></label>
        <label>{t("时区")}<select aria-label={t("时区")} value={localeForm.timezone} onChange={e => setLocaleForm({ ...localeForm, timezone: e.target.value })}>{[...new Set([localeForm.timezone, 'Asia/Shanghai', 'Asia/Tokyo', 'Europe/London', 'Europe/Amsterdam', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'UTC'])].map(zone => <option key={zone} value={zone}>{zone}</option>)}</select></label>
        <label>{t("主题")}<select value={localeForm.theme} onChange={e => setLocaleForm({ ...localeForm, theme: e.target.value })}><option value="system">{t("跟随系统")}</option><option value="light">{t("浅色")}</option><option value="dark">{t("深色")}</option></select></label>
        <label className="check-row"><input type="checkbox" checked={!!localeForm.notifications} onChange={e => setLocaleForm({ ...localeForm, notifications: e.target.checked })} />{t("启用应用通知")}</label>
        <button disabled={busy}><Save size={17} />{t("保存偏好")}</button>
      </form>
        <section className="profile-form"><h2>{t('账户安全')}</h2><p className="muted">{t('管理密码与已登录设备')}</p><button onClick={() => setTab('security')}><KeyRound size={16} />{t('修改密码')}</button></section>
      <section className="profile-form profile-danger-zone">
        <header><Trash2 size={20}/><div><h2>{t("数据与隐私")}</h2><p>{t("在统一入口导出、清除学习数据或删除账号，查看操作影响范围。")}</p></div></header>
        <Link className="text-link" to="/privacy">{t("打开隐私中心 →")}</Link>
      </section>
      </aside>
    </div>
  </div>
}
