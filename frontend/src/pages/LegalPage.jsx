import { Download } from 'lucide-react'
import { t, useI18n } from '../i18n'
import { Link, NavLink, useParams } from 'react-router-dom'
import { useAuth } from '../state/AuthContext'
import BrandLockup from '../components/BrandLockup'
import { PageHeader } from '../components/ui'
import { legalDocuments, legalUpdatedAt, legalVersion } from '../content/legal'
import '../styles/legal.css'

export default function LegalPage() {
  useI18n()
  const { document: documentId } = useParams()
  const { session } = useAuth()
  const current = Object.hasOwn(legalDocuments, documentId) ? legalDocuments[documentId] : null
  function download() {
    const text = `${t(current.title)}\n${legalVersion} · ${legalUpdatedAt}\n\n${current.sections.map(([, title, body]) => `${t(title)}\n${current.verbatim ? body : t(body)}`).join('\n\n')}`
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `Mneme-${documentId}-${legalVersion}.txt`; anchor.click(); URL.revokeObjectURL(url)
  }
  return <div className={`standard-page account-page legal-page ${session ? '' : 'legal-public'}`}>
    {!session && <header className="legal-brand"><BrandLockup to="/auth" /><Link className="text-link" to="/auth">{t('返回登录')}</Link></header>}
    <PageHeader title={t('法律与协议')} description={t('查看服务条款、隐私政策和开源许可')} />
    <nav className="legal-tabs" aria-label={t('法律文档')}>{Object.entries(legalDocuments).map(([key, value]) => <NavLink key={key} to={`/legal/${key}`} aria-current={documentId === key ? 'page' : undefined}>{t(value.title)}</NavLink>)}</nav>
    {current ? <div className="legal-layout">
      <nav className="legal-toc account-card" aria-label={t('文档目录')}><h2>{t('目录')}</h2>{current.sections.map(([id, title], index) => <a key={id} href={`#${id}`}>{index + 1}. {t(title)}</a>)}</nav>
      <article className="legal-article account-card"><header><h2>{t(current.title)}</h2><p>{t('版本')} {legalVersion} · {t('更新日期')}：{legalUpdatedAt}</p></header>
        {current.sections.map(([id, title, body], index) => <section key={id} id={id}><h3>{index + 1}. {t(title)}</h3><p className={current.verbatim ? 'preserve-space' : ''}>{current.verbatim ? body : t(body)}</p></section>)}
        <footer><div className="legal-actions"><Link className="text-link" to="/privacy">{t('管理隐私与数据')}</Link><Link className="text-link" to="/settings">{t('查看服务配置')}</Link></div><button onClick={download}><Download size={16} />{t('下载当前文档')}</button></footer>
      </article>
    </div> : <section className="account-card"><h2>{t('文档不存在')}</h2><Link className="text-link" to="/legal/terms">{t('服务条款')}</Link></section>}
  </div>
}
