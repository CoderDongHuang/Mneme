import { t, useI18n } from '../i18n'
import { statusLabel } from '../utils/statuses'

export default function StatusBadge({ status }) {
  useI18n();
  return <span className={`status-badge status-${status || 'unknown'}`}>{t(statusLabel(status, 'document'))}</span>
}
