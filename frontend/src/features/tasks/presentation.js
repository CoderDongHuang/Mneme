import { parseInstant } from '../../utils/dates'

// /workspace/operations is ordered by database ID descending. Keep that order:
// timestamps may tie and reparsing them would lose the server's tie-breaker.
export function taskEvents(logs, taskId) {
  return logs.filter(event => event.operation_id === taskId)
}

const token = value => typeof value === 'string' && /^[\w.-]{1,80}$/.test(value) ? value : null
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null
const identifier = value => typeof value === 'number' ? count(value) : token(value)

// Deliberate allowlist: never copy raw errors, filenames, payloads, paths,
// configuration or arbitrary future API fields into support diagnostics.
export function taskDiagnostics(task, events) {
  return {
    schema: 'mneme.task-diagnostics.v1',
    task: {
      task_id: token(task.task_id), task_type: token(task.task_type),
      aggregate_id: identifier(task.aggregate_id), status: token(task.status),
      attempt_count: count(task.attempt_count), max_attempts: count(task.max_attempts),
      created_at: parseInstant(task.created_at)?.toISOString() ?? null,
      updated_at: parseInstant(task.updated_at)?.toISOString() ?? null,
    },
    stages: events.map(event => ({
      step: token(event.step), status: token(event.status), attempts: count(event.attempts),
      created_at: parseInstant(event.created_at)?.toISOString() ?? null,
    })),
  }
}

export function taskFailureMessage(status) {
  if (status === 'retry') return '本次执行未成功，后台将按计划重试。'
  if (status === 'cancelling') return '取消请求已接受，正在等待后台清理；尚未完成。'
  if (status === 'cancelled') return '任务已取消。'
  return '本次执行未成功。请检查文件和服务状态，修复原因后重试；联系管理员时提供执行编号。'
}
