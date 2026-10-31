// Keep domain semantics: document processing means parsing; task processing means running.
export const taskStatusLabels = { pending: '等待领取', queued: '等待领取', processing: '执行中', running: '执行中', retry: '等待重试', cancelling: '已请求取消', failed: '失败', completed: '已完成', cancelled: '已取消', stopped: '已停止' }
const documentStatusLabels = { parsing: '解析中', processing: '解析中', ready: '可检索', partial: '部分可检索', index_pending: '词法索引待修复', index_repairing: '词法索引修复中', deleting: '删除中', delete_failed: '删除待重试', done: '可检索', pending: '等待中', queued: '等待中', ...Object.fromEntries(['cancelled', 'cancelling', 'completed', 'retry', 'failed'].map(key => [key, taskStatusLabels[key]])) }
const serviceStatusLabels = { available: '可用', not_configured: '未配置监控数据源', unavailable: '数据源不可用', up: '正常', ready: '正常', ok: '正常', healthy: '正常', down: '异常', degraded: '异常' }
const domains = { task: taskStatusLabels, document: documentStatusLabels, service: serviceStatusLabels }

export function statusLabel(value, domain = 'task') {
  const labels = Object.hasOwn(domains, domain) ? domains[domain] : null
  return labels && Object.hasOwn(labels, value) ? labels[value] : value || '未知'
}
