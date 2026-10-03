import { useState } from 'react'
export default function AdminAccess({ onUnlock }) {
  const [token, setToken] = useState('')
  return <form className="center-toolbar" onSubmit={e => { e.preventDefault(); onUnlock(token); setToken('') }}>
    <label>管理员凭证<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required minLength={32} /></label>
    <button type="submit">验证权限</button>
  </form>
}
