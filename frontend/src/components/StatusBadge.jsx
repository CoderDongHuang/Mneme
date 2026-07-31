const labels = {
  parsing: '解析中',
  processing: '解析中',
  ready: '可检索',
  done: '可检索',
  completed: '已完成',
  retry: '等待重试',
  pending: '等待中',
  queued: '等待中',
  failed: '失败',
}

export default function StatusBadge({ status }) {
  return <span className={`status-badge status-${status || 'unknown'}`}>{labels[status] || status || '未知'}</span>
}
