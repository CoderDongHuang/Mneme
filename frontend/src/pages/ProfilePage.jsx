import { Camera, KeyRound, Mail, Save, UserRound, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'
import LoadingState from '../components/LoadingState'
import { useAuth } from '../state/AuthContext'
import '../styles/profile.css'

export default function ProfilePage() {
  const { updateSession, logout } = useAuth()
  const fileInput = useRef(null)
  const [profile, setProfile] = useState(null)
  const [passwords, setPasswords] = useState({ currentPassword: '', newPassword: '', confirm: '' })
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [avatarVersion, setAvatarVersion] = useState(0)

  useEffect(() => { endpoints.profile().then(setProfile).catch((e) => setError(e.message)) }, [])
  async function run(action, success) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); setNotice(success) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function saveProfile(event) {
    event.preventDefault()
    await run(async () => { const data = await endpoints.updateProfile({ nickname: profile.nickname, email: profile.email }); setProfile(data); updateSession(data) }, '个人资料已保存')
  }
  async function upload(event) {
    const file = event.target.files?.[0]
    if (!file) return
    await run(async () => { const data = await endpoints.uploadAvatar(file); setProfile(data); const version = Date.now(); setAvatarVersion(version); updateSession({ ...data, avatarVersion: version }) }, '头像已更新')
    event.target.value = ''
  }
  async function changePassword(event) {
    event.preventDefault()
    if (passwords.newPassword !== passwords.confirm) { setError('两次输入的新密码不一致'); return }
    await run(async () => { await endpoints.changePassword({ currentPassword: passwords.currentPassword, newPassword: passwords.newPassword }); setPasswords({ currentPassword: '', newPassword: '', confirm: '' }) }, '密码已修改')
  }
  async function deleteAccount() {
    if (!window.confirm('确定删除账号及全部学习数据吗？此操作不可恢复。')) return
    await run(async () => { await endpoints.deleteAccount(); logout() }, '账号已删除')
  }

  if (!profile) return <LoadingState label="正在读取用户资料" />
  return <div className="profile-page">
    <header className="profile-hero"><p>用户中心</p><h1>管理你的学习身份</h1><span>资料仅保存在本地服务中</span></header>
    {(error || notice) && <div className={error ? 'page-error' : 'profile-notice'}>{error || notice}</div>}
    <main className="profile-layout">
      <section className="identity-panel">
        <button className="avatar-editor" onClick={() => fileInput.current?.click()} disabled={busy} title="更换头像">
          {profile.hasAvatar ? <img src={`${endpoints.avatarUrl()}?v=${avatarVersion}`} alt="当前头像" /> : <UserRound size={54} />}
          <span><Camera size={16} />更换头像</span>
        </button>
        <input ref={fileInput} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={upload} />
        <strong>{profile.nickname || profile.username}</strong><small>@{profile.username}</small>
      </section>
      <form className="profile-form" onSubmit={saveProfile}>
        <header><UserRound size={20}/><div><h2>基本资料</h2><p>设置对外显示的昵称和绑定邮箱</p></div></header>
        <label><span>昵称</span><input value={profile.nickname} maxLength="50" onChange={(e) => setProfile({...profile,nickname:e.target.value})} placeholder="输入昵称" /></label>
        <label><span>绑定邮箱</span><div className="profile-input"><Mail size={17}/><input type="email" value={profile.email} onChange={(e) => setProfile({...profile,email:e.target.value})} placeholder="用于找回密码" /></div></label>
        <button disabled={busy}><Save size={17}/>保存资料</button>
      </form>
      <form className="profile-form" onSubmit={changePassword}>
        <header><KeyRound size={20}/><div><h2>修改密码</h2><p>修改后请使用新密码再次登录</p></div></header>
        <label><span>当前密码</span><input type="password" value={passwords.currentPassword} onChange={(e)=>setPasswords({...passwords,currentPassword:e.target.value})} required /></label>
        <label><span>新密码</span><input type="password" minLength="8" value={passwords.newPassword} onChange={(e)=>setPasswords({...passwords,newPassword:e.target.value})} required /></label>
        <label><span>确认新密码</span><input type="password" minLength="8" value={passwords.confirm} onChange={(e)=>setPasswords({...passwords,confirm:e.target.value})} required /></label>
        <button disabled={busy}><KeyRound size={17}/>确认修改</button>
      </form>
      <section className="profile-form profile-danger-zone">
        <header><Trash2 size={20}/><div><h2>删除账号</h2><p>删除账号、资料库、会话和学习画像</p></div></header>
        <button type="button" disabled={busy} onClick={deleteAccount}>删除我的账号</button>
      </section>
    </main>
  </div>
}
