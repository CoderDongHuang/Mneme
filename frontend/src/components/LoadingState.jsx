import { t, useI18n } from '../i18n'
export default function LoadingState({ label = t("正在加载") }) {
  useI18n();
  return <div className="loading-state" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" />{t(label)}</div>
}
