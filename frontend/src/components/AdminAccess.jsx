import { t, useI18n } from '../i18n'
import { useState } from 'react'
export default function AdminAccess({ onUnlock }) {
  useI18n();
  const [token, setToken] = useState('')
  return <form className="center-toolbar" onSubmit={e => { e.preventDefault(); onUnlock(token); setToken('') }}>
    <label>{t("管理员凭证")}<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required minLength={32} /></label>
    <button type="submit">{t("验证权限")}</button>
  </form>
}
