import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('单会话删除跨服务失败保留任务，真实页面重试后零残留且不影响其他会话', async ({ page, playwright }, testInfo) => {
  test.setTimeout(240000)
  const container = service => {
    const ids = execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
    expect(ids).toHaveLength(1)
    return ids[0]
  }
  const agent = container('python-agent'), mysql = container('mysql')
  const sql = input => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'],
    { input, encoding: 'utf8', timeout: 20000 }).trim()
  const probe = (mode, user, target, keep) => execFileSync('docker', ['exec', agent, 'python', 'scripts/check_single_session_fence.py', mode, ...[user, target, keep].map(String)],
    { encoding: 'utf8', timeout: 30000 }).trim().split('\n').at(-1)
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  const accounts = []
  const suffix = randomUUID().replaceAll('-', '')
  const trigger = `qa_session_${suffix}`
  let target, keep, taskId
  async function api(client, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await client[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.ok(), `${method} ${path}: ${response.status()}`).toBe(true)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const tasks = () => api(page.request, 'get', '/workspace/tasks')
  async function screenshot(name) {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: true, animations: 'disabled' })
  }
  async function history() {
    const toggle = page.getByRole('button', { name: '切换会话栏' })
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click()
  }
  try {
    for (const [index, client] of [page.request, other].entries()) {
      const account = await api(client, 'post', '/auth/register', { username: `singleqa_${suffix.slice(0, 12)}_${index}`, password: `SessionQA!${suffix}` })
      expect(String(account.userId)).toMatch(/^\d+$/)
      accounts.push({ account, client })
    }
    const user = accounts[0].account.userId
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), accounts[0].account)
    target = await api(page.request, 'post', '/sessions', { title: 'Single session deletion QA' })
    keep = await api(page.request, 'post', '/sessions', { title: 'Protected session QA' })
    expect(String(target.id)).toMatch(/^\d+$/); expect(String(keep.id)).toMatch(/^\d+$/)
    expect(probe('seed', user, target.id, keep.id)).toContain('PASS: single-session deletion fence seed')
    const forbidden = await other.delete(`/api/v1/sessions/${target.id}`)
    expect((await forbidden.json()).code).not.toBe(200)
    sql(`DELIMITER $$
CREATE TRIGGER ${trigger} BEFORE DELETE ON chat_session FOR EACH ROW
BEGIN IF OLD.id=${target.id} AND OLD.user_id=${user} THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='single-session-qa-failure'; END IF; END$$
DELIMITER ;`)
    await page.goto('/chat')
    await history()
    const accepted = page.waitForResponse(response => response.url().endsWith(`/api/v1/sessions/${target.id}`) && response.request().method() === 'DELETE')
    await page.getByRole('button', { name: `删除对话：${target.title}`, exact: true }).click()
    const body = await (await accepted).json()
    expect(body.code).toBe(200)
    expect(body.data).toMatchObject({ accepted: true })
    expect(body.data).not.toHaveProperty('deleted')
    taskId = body.data.task_id; expect(taskId).toMatch(/^task_[a-zA-Z0-9_]+$/)
    sql(`UPDATE processing_task SET max_attempts=1 WHERE task_id='${taskId}' AND user_id=${user};`)
    // Mobile history overlays the chat status; dismiss it before checking notice.
    const toggle = page.getByRole('button', { name: '切换会话栏' })
    if (testInfo.project.name === '移动端' && await toggle.getAttribute('aria-expanded') === 'true') await page.locator('.history-close').click()
    await expect(page.getByText('会话删除已受理，最终清理结果请在任务中心查看。')).toBeVisible()
    await screenshot('accepted-cleanup-pending.png')
    await expect.poll(async () => (await tasks()).find(item => item.task_id === taskId)?.status,
      { timeout: 60000, intervals: [500, 1000] }).toBe('failed')
    expect(sql(`SELECT deletion_status FROM chat_session WHERE id=${target.id} AND user_id=${user};`)).toBe('delete_pending')
    expect(probe('verify', user, target.id, keep.id)).toContain('PASS: single-session deletion fence verify')
    expect((await api(page.request, 'get', '/sessions')).map(item => item.id)).toEqual([keep.id])
    const duplicate = await api(page.request, 'delete', `/sessions/${target.id}`)
    expect(duplicate).toMatchObject({ task_id: taskId, accepted: true, status: 'failed' })
    await page.getByRole('link', { name: '查看清理任务' }).click()
    await page.getByRole('button', { name: /会话删除.*尝试/ }).click()
    const details = page.getByRole(testInfo.project.name === '移动端' ? 'dialog' : 'complementary', { name: '任务详情' })
    await expect(details).toContainText('会话清理未完成，会话已隔离')
    await screenshot('failed-cleanup-retains-retry.png')
    sql(`DROP TRIGGER ${trigger};`)
    await page.getByRole('button', { name: '重试任务', exact: true }).click()
    await expect.poll(async () => (await tasks()).find(item => item.task_id === taskId)?.status,
      { timeout: 60000, intervals: [500, 1000] }).toBe('completed')
    // A mobile modal correctly makes the page beneath it inert.
    if (testInfo.project.name === '移动端') await details.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    await page.getByRole('button', { name: '刷新任务' }).click()
    if (testInfo.project.name === '移动端') await page.getByRole('button', { name: /会话删除.*尝试/ }).click()
    await expect(details).toContainText('已完成')
    await screenshot('cleanup-completed.png')
    expect(sql(`SELECT COUNT(*) FROM chat_session WHERE id=${target.id}; SELECT COUNT(*) FROM chat_message WHERE session_id=${target.id}; SELECT COUNT(*) FROM pending_memory WHERE user_id=${user} AND session_id=${target.id};`)).toBe('0\n0\n0')
    expect(probe('verify', user, target.id, keep.id)).toContain('PASS: single-session deletion fence verify')
    expect(await api(page.request, 'delete', `/sessions/${target.id}`)).toMatchObject({ task_id: taskId, status: 'completed' })
    await page.goto('/chat'); await history()
    await expect(page.getByRole('button', { name: `打开对话：${keep.title}` })).toBeVisible()
    await expect(page.getByRole('button', { name: `打开对话：${target.title}` })).toHaveCount(0)
    await screenshot('protected-session-remains.png')
    await testInfo.attach('single-session-cleanup.json', { body: JSON.stringify({ accepted_is_not_completed: true, sql_failure_retains_scope: true,
      permanent_agent_fence: true, cold_late_writes_rejected: true, manual_retry_completed: true, independent_sql_redis_manifest_zero: true,
      other_session_and_owner_protected: true, idempotent_receipt: true }), contentType: 'application/json' })
  } finally {
    // Cleanup gets its own bounded budget even when the body has timed out;
    // this does not change the recorded outcome of the body assertions.
    test.setTimeout(testInfo.timeout + 120000)
    sql(`DROP TRIGGER IF EXISTS ${trigger};`)
    for (const entry of accounts) {
      await api(entry.client, 'delete', '/profile/account')
      await expect.poll(() => sql(`SELECT status FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`),
        { timeout: 60000, intervals: [500, 1000] }).toBe('completed')
      expect(sql(`SELECT COUNT(*) FROM user WHERE id=${entry.account.userId};`)).toBe('0')
    }
    await other.dispose()
  }
})
