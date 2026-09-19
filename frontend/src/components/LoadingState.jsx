export default function LoadingState({ label = '正在加载' }) {
  return <div className="loading-state" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" />{label}</div>
}
