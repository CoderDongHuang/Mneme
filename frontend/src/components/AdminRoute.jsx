import { t, useI18n } from '../i18n'
import { Outlet } from 'react-router-dom'
import { useAuth } from '../state/AuthContext'
export default function AdminRoute() {
  useI18n();
  const { isAdmin, roleLoading } = useAuth()
  if (roleLoading) return <p className="loading-state" role="status">{t("正在验证管理员权限…")}</p>
  return isAdmin ? <Outlet /> : <div className="standard-page"><h1>{t("无访问权限")}</h1><p role="alert">{t("此页面仅向管理员开放。")}</p></div>
}
