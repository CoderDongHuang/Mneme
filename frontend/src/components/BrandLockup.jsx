import { Link } from 'react-router-dom'
import { t } from '../i18n'
import logo from '../assets/mneme-logo.svg'
import '../styles/brand.css'

export default function BrandLockup({ to = '/chat', onClick, className = '' }) {
  return <Link to={to} onClick={onClick} className={`brand-lockup ${className}`} aria-label="Mneme">
    <img src={logo} alt="" /><span><strong>Mneme <em>{t('忆知')}</em></strong><small>{t('让知识成为你的长期记忆')}</small></span>
  </Link>
}
