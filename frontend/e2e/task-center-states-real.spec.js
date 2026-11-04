import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、MySQL 和 Agent')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('任务与阶段读取独立，真实重试提交后断网保留回执并拒绝重复写入', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', ''), taskId = `taskqa_${suffix}`, step = `qa_stage_${suffix.slice(0, 8)}`
  let account, failTasks = true, failLogs = false, taskReads = 0, logReads = 0, writes = 0
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, { data, timeout: 15000 })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      return body.data
    }
  }
  const tasksStatus = () => page.getByRole('region', { name: '任务读取状态', exact: true })
  const logsStatus = () => page.getByRole('region', { name: '阶段记录读取状态', exact: true })
  try {
    account = await api('post', '/auth/register', { username: `taskqa_${suffix.slice(0, 12)}`, password: `TaskQA!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    // Seed only a disposable user's cleanup task. A missing document makes its
    // retry safe and idempotent; the real worker performs the cleanup path.
    const documentId = 8_000_000_000_000_000 + Number(account.userId)
    expect(sql(`SELECT COUNT(*) FROM knowledge_document WHERE id=${documentId}`)).toBe('0')
    sql(`INSERT INTO processing_task(task_id,user_id,task_type,aggregate_id,idempotency_key,payload,status,attempt_count,max_attempts,error_message) VALUES ('${taskId}',${account.userId},'document_delete',${documentId},'${taskId}',JSON_OBJECT('user_id','${account.userId}','document_id','doc_${documentId}','kb_id','kb_${documentId}','file_path','/data/files/${taskId}.txt'),'failed',3,3,'QA failure'); INSERT INTO operation_log(operation_id,user_id,operation_type,step,status) VALUES ('${taskId}',${account.userId},'document_delete','${step}','failed');`)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    // Isolate manual GET retries from worker notification-triggered refreshes.
    // The hook's notification subscription is covered separately by unit tests.
    await page.route('**/api/v1/notifications/stream', route => route.abort('internetdisconnected'))
    await page.route('**/api/v1/workspace/tasks', route => {
      taskReads++
      return failTasks ? route.abort('internetdisconnected') : route.continue()
    })
    await page.route('**/api/v1/workspace/operations?*', route => {
      logReads++
      return failLogs ? route.abort('internetdisconnected') : route.continue()
    })
    await page.route(`**/api/v1/workspace/tasks/${taskId}/retry`, async route => {
      writes++
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      expect((await response.json()).data).toEqual({ task_id: taskId, status: 'retry' })
      failTasks = true; failLogs = true
      await route.fulfill({ response })
    })
    await page.goto('/tasks')
    await expect(tasksStatus().getByRole('alert')).toContainText('任务列表加载失败')
    await expect(page.locator('.activity-timeline')).toContainText(step)
    await expect(page.getByText('暂无符合条件的任务', { exact: true })).toHaveCount(0)
    await expect(page.locator('.reference-metrics')).toContainText('—')
    const beforeLogs = logReads
    failTasks = false
    await tasksStatus().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await page.getByRole('region', { name: '任务列表', exact: true }).getByRole('button', { name: /文档删除/ }).click()
    expect(logReads).toBe(beforeLogs)
    const detail = () => page.getByRole(page.viewportSize().width < 1280 ? 'dialog' : 'complementary', { name: '任务详情', exact: true })
    await expect(detail()).toContainText(taskId)
    await detail().getByRole('button', { name: '重试任务', exact: true }).click({ timeout: 10000 })
    await expect(detail()).toContainText('重试已提交，原失败记录保留在阶段日志中')
    await expect(tasksStatus().getByRole('alert')).toContainText('已有记录可能不是最新状态')
    await expect(logsStatus().getByRole('alert')).toContainText('阶段记录加载失败')
    await expect(detail().getByRole('button', { name: '重试任务', exact: true })).toBeDisabled()
    expect(writes).toBe(1)
    expect(sql(`SELECT COUNT(*) FROM processing_task WHERE user_id=${account.userId} AND task_id='${taskId}' AND status<>'failed'`)).toBe('1')
    const beforeTasks = taskReads
    failLogs = false
    await logsStatus().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(logsStatus().getByRole('alert')).toHaveCount(0)
    expect(taskReads).toBe(beforeTasks)
    expect(writes).toBe(1)
    await expect(detail()).toContainText('重试已提交')
    // A read-only retry is allowed to fail repeatedly; it never resends POST.
    await tasksStatus().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(tasksStatus().getByRole('alert')).toContainText('任务列表加载失败')
    expect(writes).toBe(1)
    await expect(detail()).toContainText('重试已提交')
    await page.screenshot({ path: testInfo.outputPath('task-center-stale-receipt.png'), fullPage: false })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    failTasks = false
    await tasksStatus().getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(tasksStatus().getByRole('alert')).toHaveCount(0)
    expect(writes).toBe(1)
    await expect.poll(() => sql(`SELECT status FROM processing_task WHERE user_id=${account.userId} AND task_id='${taskId}'`), { timeout: 60000, intervals: [1000] }).toBe('completed')
  } finally {
    if (account) {
      test.setTimeout(testInfo.timeout + 90000)
      await page.close()
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
      expect(sql(`SELECT COUNT(*) FROM processing_task WHERE user_id=${account.userId}`)).toBe('0')
    }
  }
})
