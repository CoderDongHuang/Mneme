import { t, useI18n } from '../i18n'
import { Camera, KeyRound, Mail, Save, UserRound, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'
import LoadingState from '../components/LoadingState'
import { useAuth } from '../state/AuthContext'
import { usePreferences } from '../state/PreferencesContext'
import { Link } from 'react-router-dom'
import { FeedbackBlock, PageHeader } from '../components/ui'
import ProfileSessions from '../features/profile/ProfileSessions'
import useProfileData from '../features/profile/useProfileData'
import { validEmailReceipt } from '../features/profile/profileValidation'
import '../styles/profile.css'

export default function ProfilePage() {
  const { session } = useAuth()
  return <ProfileView key={session?.userId || session?.username || 'profile'} />
}

function ProfileView() {
  useI18n()
  const { session, updateSession, logout } = useAuth()
  const { preferences, save: savePreferences, error: preferenceError } = usePreferences()
  const [localeForm, setLocaleForm] = useState(preferences)
  const [tab, setTab] = useState('basic')
  useEffect(() => { setLocaleForm(preferences) }, [preferences])
  const fileInput = useRef(null)
  const { profile, setProfile, saved, loading: profileLoading, readError: profileError, error, setError, notice, busy, pending, checked, avatarVersion, load: retryProfile, resolve, run } = useProfileData(session, updateSession)
  const savedEmail = saved?.email || ''
  const [emailToken, setEmailToken] = useState('')
  const [emailSent, setEmailSent] = useState(false)
  const [passwords, setPasswords] = useState({ currentPassword: '', newPassword: '', confirm: '' })
  const formLocked = busy || pending || profileLoading
  useEffect(() => { setEmailToken(''); setEmailSent(false) }, [saved])

  async function saveProfile(event) {
    event.preventDefault()
    const submitted = { nickname: profile.nickname, email: profile.email }
    await run(options => endpoints.updateProfile(submitted, options), t('个人资料已保存'), {
      profileResult: true, protect: true,
      valid: value => value && (value.nickname || '') === (submitted.nickname || '').trim() && (value.email || '').toLowerCase() === (submitted.email || '').trim().toLowerCase(),
    })
  }
  async function requestEmail() {
    await run(options => endpoints.requestEmailVerification(savedEmail, options), t('验证邮件已提交至邮件服务器，请检查收件箱。验证码 15 分钟内有效。'), { valid: validEmailReceipt, protect: true, onSuccess: () => setEmailSent(true) })
  }
  async function confirmEmail(event) {
    event.preventDefault()
    await run(options => endpoints.confirmEmailVerification(emailToken.trim(), options), t('邮箱验证成功，现在可以用于找回密码。'), { profileResult: true, protect: true, valid: value => value?.emailVerified === true && (value.email || '').toLowerCase() === savedEmail.toLowerCase() })
  }
  async function upload(event) {
    const file = event.target.files?.[0]
    if (!file) return
    const input = event.target
    await run(options => endpoints.uploadAvatar(file, options), t('头像已更新'), { profileResult: true, protect: true, valid: value => value?.hasAvatar === true })
    input.value = ''
  }
  async function changePassword(event) {
    event.preventDefault()
    if (passwords.newPassword !== passwords.confirm) { setError(t("两次输入的新密码不一致")); return }
    await run(options => endpoints.changePassword({ currentPassword: passwords.currentPassword, newPassword: passwords.newPassword }, options), t('密码已修改，请重新登录'), { valid: value => value === null, onSuccess: () => { setPasswords({ currentPassword: '', newPassword: '', confirm: '' }); logout() } })
  }

  if (!profile) return <div className="standard-page account-page profile-page">
    <PageHeader title={t('个人资料')} description={t('管理个人信息、账户安全和偏好设置')} />
    {profileLoading ? <LoadingState label={t('正在读取用户资料')} /> : <FeedbackBlock error={profileError} onRetry={retryProfile} />}
  </div>
  const emailChanged = (profile.email || '').trim().toLowerCase() !== savedEmail.trim().toLowerCase()
  return <div className="standard-page account-page profile-page">
    <PageHeader title={t('个人资料')} description={t('管理个人信息、账户安全和偏好设置')} />
    <FeedbackBlock error={error} message={notice} />
    {pending && <section className="profile-form" aria-label={t('核对个人资料')}>
      <p>{t('草稿已保留。核对只读取资料，不会再次保存、上传或发送邮件；邮箱验证状态不能证明邮件是否送达。')}</p>
      <button type="button" disabled={profileLoading} onClick={retryProfile}>{t('核对已保存资料')}</button>
      <FeedbackBlock error={profileError} />
      {checked && <>
        <dl><dt>{t('昵称')}</dt><dd>{checked.nickname || checked.username}</dd><dt>{t('绑定邮箱')}</dt><dd>{checked.email || '—'}</dd><dt>{t('邮箱验证')}</dt><dd>{t(checked.emailVerified ? '已验证' : '未验证')}</dd><dt>{t('头像')}</dt><dd>{t(checked.hasAvatar ? '已设置' : '未设置')}</dd></dl>
        <button type="button" onClick={() => resolve(true)}>{t('采用服务端资料')}</button>{' '}
        <button type="button" onClick={() => resolve(false)}>{t('保留草稿，继续编辑')}</button>
      </>}
    </section>}
    <div className="account-columns">
      <div className="account-main">
        <nav className="segmented-tabs" aria-label={t('个人资料分组')}><button aria-pressed={tab === 'basic'} onClick={() => setTab('basic')}>{t('基本资料')}</button><button aria-pressed={tab === 'security'} onClick={() => setTab('security')}>{t('账户安全')}</button></nav>
        <div hidden={tab !== 'basic'} className="profile-basics">
      <section className="identity-panel">
        <button className="avatar-editor" onClick={() => fileInput.current?.click()} disabled={formLocked} title={t("更换头像")}>
          {profile.hasAvatar ? <img src={`${endpoints.avatarUrl()}?v=${avatarVersion}`} alt={t("当前头像")} /> : <UserRound size={54} />}
          <span><Camera size={16} />{t("更换头像")}</span>
        </button>
        <input ref={fileInput} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={upload} />
        <div><strong>{profile.nickname || profile.username}</strong><small>@{profile.username}</small><p>{t("资料、偏好与账户安全")}</p></div>
      </section>
      <form className="profile-form" onSubmit={saveProfile}>
        <header><UserRound size={20}/><div><h2>{t("基本资料")}</h2><p>{t("设置对外显示的昵称和绑定邮箱")}</p></div></header>
        <label><span>{t("昵称")}</span><input disabled={formLocked} value={profile.nickname ?? ''} maxLength="50" onChange={(e) => setProfile({...profile,nickname:e.target.value})} placeholder={t("输入昵称")} /></label>
        <label><span>{t("绑定邮箱")}</span><div className="profile-input"><Mail size={17}/><input disabled={formLocked} type="email" maxLength={120} value={profile.email ?? ''} onChange={(e) => setProfile({...profile,email:e.target.value})} placeholder={t("用于找回密码")} /></div></label>
        <button disabled={formLocked}><Save size={17}/>{t("保存资料")}</button>
      </form>
      <section className="profile-form email-verification" aria-labelledby="email-verification-title">
        <h2 id="email-verification-title">{t('邮箱验证')}</h2>
        <p role="status">{emailChanged ? t('邮箱有未保存的修改，请先保存资料。') : profile.emailVerified ? t('当前邮箱已验证，可用于找回密码。') : t('当前邮箱尚未验证，不能用于找回密码。')}</p>
        {!emailChanged && !profile.emailVerified && savedEmail && <>
          <button type="button" disabled={formLocked} onClick={requestEmail}>{t(emailSent ? '重新发送验证码' : '发送邮箱验证码')}</button>
          <p className="muted">{t('请复制邮件中的完整验证码；重新发送需间隔 60 秒，新验证码会使旧验证码失效。')}</p>
          <form onSubmit={confirmEmail}>
            <label>{t('邮箱验证码')}<input disabled={formLocked} value={emailToken} onChange={event => setEmailToken(event.target.value)} autoComplete="one-time-code" spellCheck={false} minLength={64} maxLength={64} pattern="[0-9a-f]{64}" required /></label>
            <button disabled={formLocked || emailToken.trim().length !== 64}>{t('验证邮箱')}</button>
          </form>
        </>}
      </section>
        </div>
        <div hidden={tab !== 'security'} className="profile-security">
      <form className="profile-form" onSubmit={changePassword}>
        <header><KeyRound size={20}/><div><h2>{t("修改密码")}</h2><p>{t("修改后请使用新密码再次登录")}</p></div></header>
        <label><span>{t("当前密码")}</span><input disabled={formLocked} type="password" value={passwords.currentPassword} onChange={(e)=>setPasswords({...passwords,currentPassword:e.target.value})} required /></label>
        <label><span>{t("新密码")}</span><input disabled={formLocked} type="password" minLength="8" value={passwords.newPassword} onChange={(e)=>setPasswords({...passwords,newPassword:e.target.value})} required /></label>
        <label><span>{t("确认新密码")}</span><input disabled={formLocked} type="password" minLength="8" value={passwords.confirm} onChange={(e)=>setPasswords({...passwords,confirm:e.target.value})} required /></label>
        <button disabled={formLocked}><KeyRound size={17}/>{t("确认修改")}</button>
      </form>
      {tab === 'security' && <ProfileSessions language={localeForm.language} timezone={localeForm.timezone} disabled={formLocked} />}
        </div>
      </div>
      <aside className="account-aside">
      <form className="profile-form" onSubmit={event => { event.preventDefault(); run(async () => { await savePreferences(localeForm) }, t("偏好已保存")) }}>
        <h2>{t("语言与偏好")}</h2><FeedbackBlock error={preferenceError} />
        <label>{t("界面语言")}<select disabled={formLocked} aria-label={t("界面语言")} value={localeForm.language} onChange={e => setLocaleForm({ ...localeForm, language: e.target.value })}><option value="zh-CN">{t("简体中文")}</option><option value="en">English</option></select></label>
        <label>{t("时区")}<select disabled={formLocked} aria-label={t("时区")} value={localeForm.timezone} onChange={e => setLocaleForm({ ...localeForm, timezone: e.target.value })}>{[...new Set([localeForm.timezone, 'Asia/Shanghai', 'Asia/Tokyo', 'Europe/London', 'Europe/Amsterdam', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'UTC'])].map(zone => <option key={zone} value={zone}>{zone}</option>)}</select></label>
        <label>{t("主题")}<select disabled={formLocked} value={localeForm.theme} onChange={e => setLocaleForm({ ...localeForm, theme: e.target.value })}><option value="system">{t("跟随系统")}</option><option value="light">{t("浅色")}</option><option value="dark">{t("深色")}</option></select></label>
        <label className="check-row"><input disabled={formLocked} type="checkbox" checked={!!localeForm.notifications} onChange={e => setLocaleForm({ ...localeForm, notifications: e.target.checked })} />{t("启用应用通知")}</label>
        <button disabled={formLocked}><Save size={17} />{t("保存偏好")}</button>
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
