export default function LoadingState({ label = '正在加载' }) {
  return <div className="loading-state"><span className="spinner" />{label}</div>
}
