import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_MEMORY_QA_FAULTS !== 'true', '需要真实服务及隔离数据库故障注入')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('候选记忆入库失败不覆盖已完成回答，重启后真实重试与确认可读且不重复', async ({ page }, testInfo) => {
  test.setTimeout(300_000)
  page.setDefaultTimeout(15000)
  const container = service => execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  // Old deployment containers are stopped; only one active service may match.
  const agent = container('python-agent'), gateway = container('java-gateway'), mysql = container('mysql')
  for (const id of [agent, gateway, mysql]) expect(id).toMatch(/^[a-f0-9]+$/)
  const python = (code, ...args) => execFileSync('docker', ['exec', '--user', '0', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30_000 }).trim().split('\n').at(-1)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30_000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  const trigger = `qa_memory_${suffix}`
  let account, folder, session, taskId, assistantId
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const payload = await response.json(); expect(payload.code).toBe(200)
      return payload.data
    }
    throw new Error('Rate limit did not recover')
  }
  async function restart(id, health) {
    execFileSync('docker', ['restart', id], { timeout: 40_000, stdio: 'pipe' })
    await expect.poll(async () => {
      try { return (await page.request.get(health, { timeout: 3000 })).ok() } catch { return false }
    }, { timeout: 90_000, intervals: [1000] }).toBe(true)
  }
  const tasks = () => api('get', '/workspace/tasks')
  const memoryTask = async () => (await tasks()).find(t => t.task_type === 'memory_candidates')
  async function screenshot(name) {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    account = await api('post', '/auth/register', { username: `memout_${suffix.slice(0, 12)}`, password: `MemoryQA!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    session = await api('post', '/sessions', { title: 'Memory outbox QA' })
    const owner = JSON.parse(execFileSync('docker', ['exec', agent, 'python', '-c', 'import os,json; print(json.dumps([os.getuid(),os.getgid()]))'], { encoding: 'utf8' }))
    const fixture = fs.readFileSync('../test-fixtures/memory-outbox-probe.py', 'utf8')
    folder = python("import tempfile\nprint(tempfile.mkdtemp(prefix='mneme-memory-qa-'))")
    expect(folder).toMatch(/^\/tmp\/mneme-memory-qa-/)
    const scope = { user: String(account.userId), session: String(session.id), memory: `memqa_${suffix}` }
    python(`import os,json,sys
from pathlib import Path
root=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-memory-qa-')
module=Path('/app/app/api/chat_stream.py')
(root/'original').write_bytes(module.read_bytes())
(root/'scope.json').write_text(sys.argv[2])
(root/'probe.py').write_text(sys.argv[3])
suffix=('\\nfrom pathlib import Path as _QaPath\\n_qa_root = _QaPath('+repr(str(root))+')\\nexec(compile((_qa_root / "probe.py").read_text(), str(_qa_root / "probe.py"), "exec"), globals())\\n').encode()
(root/'suffix').write_bytes(suffix)
os.chown(root,*json.loads(sys.argv[4]))
module.write_bytes((root/'original').read_bytes()+suffix)
print('installed')`, folder, JSON.stringify(scope), fixture, JSON.stringify(owner))
    await restart(agent, 'http://127.0.0.1:8001/health/ready')
    sql(`DELIMITER $$
CREATE TRIGGER ${trigger} BEFORE INSERT ON pending_memory FOR EACH ROW
BEGIN IF NEW.user_id=${account.userId} THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='private-candidate-qa-marker'; END IF; END$$
DELIMITER ;`)
    await page.goto(`/chat?session=${session.id}`)
    await expect(page.locator('.chat-heading')).toContainText(session.title)
    // Use the existing deterministic general intent; this test scopes the model
    // output, not the separate intent classifier's network latency.
    await page.getByRole('textbox', { name: '向忆知提问...' }).fill('hello')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.locator('.message-assistant')).toContainText('Candidate memory QA verified answer')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
    await expect(page.getByText('回答已保存，候选记忆正在后台保存。')).toBeVisible()
    await expect(page.getByRole('button', { name: '确认记忆', exact: true })).toHaveCount(0)
    const messages = await api('get', `/sessions/${session.id}/messages`)
    const saved = messages.find(m => m.role === 'assistant'); assistantId = saved.id
    expect(saved).toMatchObject({ status: 'completed', errorCode: null, content: 'Candidate memory QA verified answer' })
    await expect.poll(async () => (await memoryTask())?.status, { timeout: 45_000, intervals: [1000] }).toBe('failed')
    const failed = await memoryTask(); taskId = failed.task_id
    expect(failed.attempt_count).toBe(failed.max_attempts)
    expect(failed.error_message).not.toContain('private-candidate-qa-marker')
    expect(sql(`SELECT COUNT(*) FROM pending_memory WHERE user_id=${account.userId}`)).toBe('0')
    await screenshot('answer-retained.png')
    // A real process restart must preserve both the successful answer and retryable work.
    await restart(gateway, '/api/v1/health')
    expect((await memoryTask()).status).toBe('failed')
    await page.goto('/tasks')
    await page.getByRole('button', { name: /候选记忆保存/ }).click()
    const detail = page.getByRole('complementary', { name: '任务详情' })
      .or(page.getByRole('dialog', { name: '任务详情', exact: true }))
    await expect(detail).toContainText('来源回答')
    await expect(detail).toContainText('回答已保留')
    await expect(detail).not.toContainText('private-candidate-qa-marker')
    await screenshot('memory-task-failed.png')
    sql(`DROP TRIGGER ${trigger}`)
    await page.getByRole('button', { name: '重试任务', exact: true }).click()
    await expect.poll(async () => (await memoryTask()).status, { timeout: 30_000, intervals: [1000] }).toBe('completed')
    expect(sql(`SELECT JSON_LENGTH(payload) FROM processing_task WHERE task_id='${taskId}'`)).toBe('0')
    expect(sql(`SELECT COUNT(*) FROM pending_memory WHERE user_id=${account.userId} AND source_message_id=${assistantId}`)).toBe('1')
    const persisted = (await api('get', `/sessions/${session.id}/messages`)).find(m => m.id === assistantId)
    expect(persisted).toEqual(saved)
    // Replaying the same answer never starts another candidate task.
    const request = { session_id: String(session.id), request_id: saved.requestId, message: 'hello' }
    expect((await api('post', '/chat', request)).answer).toBe(saved.content)
    expect((await tasks()).filter(t => t.task_type === 'memory_candidates')).toHaveLength(1)
    await page.goto('/memory')
    await expect(page.getByText('Candidate memory QA preference')).toBeVisible()
    // Confirmation uses the real embedding/vector service. Await its bounded
    // response before checking the immediate UI receipt; do not retry a write.
    const confirmation = page.waitForResponse(response => response.url().endsWith('/api/v1/memory/confirm') && response.request().method() === 'POST', { timeout: 60_000 })
    await page.getByRole('button', { name: '确认记住', exact: true }).click()
    const confirmed = await confirmation
    expect(confirmed.status()).toBe(200)
    expect((await confirmed.json()).code).toBe(200)
    await expect(page.getByText('记忆已确认', { exact: true })).toBeVisible()
    expect(sql(`SELECT status FROM pending_memory WHERE user_id=${account.userId}`)).toBe('confirmed')
    await page.reload()
    await expect(page.getByRole('region', { name: '记忆列表' })).toContainText('Candidate memory QA preference')
    await screenshot('memory-confirmed.png')
    await page.goto(`/chat?session=${session.id}`)
    await expect(page.locator('.message-assistant')).toContainText(saved.content)
    await expect(page.locator('.message-assistant [role="alert"]')).toHaveCount(0)
    await testInfo.attach('memory-outbox.json', { body: JSON.stringify({ sql_fault: true, answer_retained: true, restart: true, manual_retry: true, candidate_count: 1, payload_purged: true, confirmed: true, replay_idempotent: true }), contentType: 'application/json' })
  } finally {
    sql(`DROP TRIGGER IF EXISTS ${trigger}`)
    if (folder) {
      python(`import sys,shutil
from pathlib import Path
root=Path(sys.argv[1]); assert str(root).startswith('/tmp/mneme-memory-qa-')
module=Path('/app/app/api/chat_stream.py')
if (root/'original').exists():
 original=(root/'original').read_bytes(); current=module.read_bytes()
 assert current==original or ((root/'suffix').exists() and current==original+(root/'suffix').read_bytes())
 module.write_bytes(original); assert module.read_bytes()==original
shutil.rmtree(root)
print('restored')`, folder)
      await restart(agent, 'http://127.0.0.1:8001/health/ready')
    }
    if (account) await api('delete', '/profile/account')
  }
})
