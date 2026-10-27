const labels = {
  parsing: '解析中',
  processing: '解析中',
  ready: '可检索',
  partial: '部分可检索',
  deleting: '删除中',
  delete_failed: '删除待重试',
  cancelled: '已取消',
  cancelling: '取消中',
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
