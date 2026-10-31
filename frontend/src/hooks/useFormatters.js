import { usePreferences } from '../state/PreferencesContext'
import { formatBytes, formatDecimal, formatNumber, formatPercent } from '../utils/formatters'
import { statusLabel } from '../utils/statuses'
import { t } from '../i18n'

export function useFormatters() {
  const { preferences: { language } } = usePreferences()
  return {
    number: (value, options) => formatNumber(value, language, options),
    integer: value => formatNumber(value, language, { maximumFractionDigits: 0 }),
    decimal: (value, digits) => formatDecimal(value, language, digits),
    percent: (ratio, digits) => formatPercent(ratio, language, digits),
    bytes: (value, digits) => formatBytes(value, language, digits),
    status: (value, domain) => t(statusLabel(value, domain)),
  }
}
