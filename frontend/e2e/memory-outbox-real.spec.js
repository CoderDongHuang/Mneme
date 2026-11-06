import { expect, test } from '@playwright/test'
import { execFileSync, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_MEMORY_QA_FAULTS !== 'true', '需要真实服务及隔离数据库故障注入')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('后台记忆失败不覆盖回答，冷启动重放与真实重试确认不重复', async ({ page }, testInfo) => {
  test.setTimeout(300_000)
  page.setDefaultTimeout(15000)
  const container = service => execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  // Old deployment containers are stopped; only one active service may match.
  const agent = container('python-agent'), gateway = container('java-gateway'), mysql = container('mysql')
  for (const id of [agent, gateway, mysql]) expect(id).toMatch(/^[a-f0-9]+$/)
  const python = (code, ...args) => execFileSync('docker', ['exec', '--user', '0', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30_000 }).trim().split('\n').at(-1)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30_000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  const privacyCanary = `MNEME_PRIVATE_PROVIDER_${suffix}`
  const logStart = new Date().toISOString()
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
  const memoryTask = async () => (await tasks()).find(t => t.task_type === 'memory_completion')
  async function screenshot(name) {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    account = await api('post', '/auth/register', { username: `memout_${suffix.slice(0, 12)}`, password: `MemoryQA!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    session = await api('post', '/sessions', { title: 'Memory outbox QA' })
    sql(`INSERT INTO chat_message(session_id,role,content,status,request_id,created_at) VALUES
      (${session.id},'user','Historical snapshot preference','completed','seed',UTC_TIMESTAMP()-INTERVAL 20 MINUTE),
      (${session.id},'assistant','Prior snapshot answer','completed','seed',UTC_TIMESTAMP()-INTERVAL 20 MINUTE)` )
    const owner = JSON.parse(execFileSync('docker', ['exec', agent, 'python', '-c', 'import os,json; print(json.dumps([os.getuid(),os.getgid()]))'], { encoding: 'utf8' }))
    const fixture = fs.readFileSync('../test-fixtures/memory-outbox-probe.py', 'utf8')
    folder = python("import tempfile\nprint(tempfile.mkdtemp(prefix='mneme-memory-qa-'))")
    expect(folder).toMatch(/^\/tmp\/mneme-memory-qa-/)
    const scope = { user: String(account.userId), session: String(session.id), privacy_canary: privacyCanary }
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
    await expect(page.locator('.message-assistant').filter({ hasText: 'Candidate memory QA verified answer' })).toHaveCount(1)
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
    await expect(page.getByText('回答已保存，记忆正在后台处理。')).toBeVisible()
    await expect(page.getByRole('button', { name: '确认记忆', exact: true })).toHaveCount(0)
    const messages = await api('get', `/sessions/${session.id}/messages`)
    const saved = messages.find(m => m.role === 'assistant' && m.content === 'Candidate memory QA verified answer'); assistantId = saved.id
    expect(saved).toMatchObject({ status: 'completed', errorCode: null, content: 'Candidate memory QA verified answer' })
    await expect.poll(async () => (await memoryTask())?.status, { timeout: 60_000, intervals: [1000] }).toBe('failed')
    expect(JSON.parse(python("import sys\nfrom pathlib import Path\nprint((Path(sys.argv[1])/'snapshot-check.json').read_text())", folder)))
      .toEqual({ snapshot_frozen: true, candidate_stable: true, actual_completion: true, reflection_delivery_recorded: true,
        distillation_failure_visible: true, distillation_retry_valid: true, session_count_delivery_deduplicated: true })
    // A separate interpreter reads the actual durable manifest and account fence.
    // Cold metadata replay must retain the same durable delivery receipt.
    expect(python(`import sys
from app.memory.session_store import session_store as store
user,session,delivery=sys.argv[1:]
before=store.get_sessions(user)
assert next(row for row in before if row['id']==session)['message_count']==2
store.register_session(user,session,delivery_id=delivery)
store.increment_message_count(user,session,delivery_id=delivery)
assert store.get_sessions(user)==before
print('durable delivery verified')`, String(account.userId), String(session.id), saved.requestId)).toBe('durable delivery verified')
    // Cold interpreter, actual SQL history and receipts; Redis is deliberately
    // unavailable to this isolated process only. Background replay is checked separately.
    expect(python(`import sys
from unittest.mock import patch
from app.memory.short_term_memory import ShortTermMemoryManager
from app.memory.session_persistence import session_persistence
from app.knowledge.generations import generation_store
from app.models.chat import Message
user,session,delivery=sys.argv[1:]
with patch.object(session_persistence,'_ensure_connection',return_value=False):
 manager=ShortTermMemoryManager()
 before=manager.get_history(session,user_id=user)
 assert any(m.content=='Candidate memory QA verified answer' for m in before)
 state=generation_store.snapshot(user)
 for role,content in [('user','hello'),('assistant','Candidate memory QA verified answer')]:
  manager.add_message(session,Message(role=role,content=content,timestamp='retry'),user_id=user,delivery_id=delivery)
 assert manager.get_history(session,user_id=user)==before
 assert generation_store.snapshot(user)==state
print('durable history verified')`, String(account.userId), String(session.id), saved.requestId)).toBe('durable history verified')
    expect(JSON.parse(python("import sys\nfrom pathlib import Path\nprint((Path(sys.argv[1])/'privacy-check.json').read_text())", folder)))
      .toEqual({ intent_fallback: true, suggestion_fallback: true, summary_history_preserved: true, real_trace_redacted: true, redis_session_diagnostics_redacted: true })
    await expect.poll(async () => (await memoryTask())?.status, { timeout: 45_000, intervals: [1000] }).toBe('failed')
    const failed = await memoryTask(); taskId = failed.task_id
    expect(failed.attempt_count).toBe(failed.max_attempts)
    expect(failed.error_message).not.toContain('private-candidate-qa-marker')
    expect(sql(`SELECT COUNT(*) FROM pending_memory WHERE user_id=${account.userId}`)).toBe('0')
    await screenshot('answer-retained.png')
    // A real process restart must preserve both the successful answer and retryable work.
    await restart(agent, 'http://127.0.0.1:8001/health/ready')
    await restart(gateway, '/api/v1/health')
    expect((await memoryTask()).status).toBe('failed')
    await page.goto('/tasks')
    await page.getByRole('button', { name: /对话记忆处理/ }).click()
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
    expect(Number(sql(`SELECT MAX(CHAR_LENGTH(memory_id)) FROM pending_memory WHERE user_id=${account.userId}`))).toBeLessThanOrEqual(64)
    const persisted = (await api('get', `/sessions/${session.id}/messages`)).find(m => m.id === assistantId)
    expect(persisted).toEqual(saved)
    // Replaying the same answer never starts another candidate task.
    const request = { session_id: String(session.id), request_id: saved.requestId, message: 'hello' }
    expect((await api('post', '/chat', request)).answer).toBe(saved.content)
    expect((await tasks()).filter(t => t.task_type === 'memory_completion')).toHaveLength(1)
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
    await expect(page.getByRole('region', { name: '记忆列表', exact: true })).toContainText('Candidate memory QA preference')
    await screenshot('memory-confirmed.png')
    await page.goto(`/chat?session=${session.id}`)
    await expect(page.locator('.message-assistant').filter({ hasText: saved.content })).toHaveCount(1)
    await expect(page.locator('.message-assistant [role="alert"]')).toHaveCount(0)
    // Expire only this QA user's SQL history; do not invoke the cleanup helper.
    // The running Agent's real minute scheduler must reclaim unread bodies.
    expect(python(`import sys
from datetime import timedelta
from app.core.time import utc_now
from app.knowledge.generations import generation_store
from app.memory.short_term_memory import ShortTermMemoryManager
from app.memory.session_history import session_key
from app.memory.completion import _digest
from app.models.chat import MemoryCompletion
from pathlib import Path
from app.models.chat import Message
user,session,folder=sys.argv[1:]
request=MemoryCompletion.model_validate_json((Path(folder)/'completion-request.json').read_text())
old=request.model_copy(update={'delivery_id':'retention-expired','reference_time':(utc_now()-timedelta(days=3660)).isoformat()})
(Path(folder)/'expired-request.json').write_text(old.model_dump_json())
manager=ShortTermMemoryManager()
for name in ['retention-orphan','retention-active']:
 manager.add_message(name,Message(role='user',content='isolated retention QA',timestamp=utc_now().isoformat()),user_id=user,delivery_id='retention')
with generation_store.locked(user) as state:
 jobs=state['memory_completions'][session_key(session)]
 assert jobs[_digest(request.delivery_id)]['reference_time']==request.reference_time
 jobs[_digest(old.delivery_id)]={'fingerprint':_digest(old.model_dump()),'created_at':old.reference_time,'reference_time':old.reference_time,'phases':{'history':True}}
 jobs['legacy-qa']={'fingerprint':'f'*64,'created_at':old.reference_time,'phases':{'history':True}}
 for name in [session,'retention-orphan']:
  state['session_histories'][session_key(name)]['expires_at']=(utc_now()-timedelta(seconds=1)).timestamp()
print('expiry seeded')`, String(account.userId), String(session.id), folder)).toBe('expiry seeded')
    await expect.poll(() => python(`import sys
from app.knowledge.generations import generation_store
from app.memory.session_history import session_key
from app.memory.completion import _digest
user,session=sys.argv[1:]
state=generation_store.snapshot(user)
histories=state['session_histories']
assert histories[session_key('retention-active')]['deliveries']
jobs=state['memory_completions'][session_key(session)]
assert 'legacy-qa' in jobs
print(all(histories[session_key(name)]=={'expired':True} for name in [session,'retention-orphan']) and _digest('retention-expired') not in jobs and len(jobs)==2)`, String(account.userId), String(session.id)),
    { timeout: 90_000, intervals: [3000] }).toBe('True')
    expect(python(`import sys
from pathlib import Path
from unittest.mock import patch
from app.memory.completion import complete_memory
from app.memory.session_store import session_store
from app.knowledge.generations import generation_store
from app.models.chat import MemoryCompletion
user,folder=sys.argv[1:]
request=MemoryCompletion.model_validate_json((Path(folder)/'expired-request.json').read_text())
assert request.user_id==user
before=generation_store.snapshot(user)
manifest=session_store.get_sessions(user)
with patch('app.memory.completion._extract',side_effect=AssertionError('expired provider called')):
 try: complete_memory(request)
 except ValueError as error: assert '保留期' in str(error)
 else: raise AssertionError('expired replay accepted')
assert generation_store.snapshot(user)==before
assert session_store.get_sessions(user)==manifest
print('expired completion fenced')`, String(account.userId), folder)).toBe('expired completion fenced')
    // Gateway's permanent answer remains readable after short context expires.
    await page.reload()
    await expect(page.locator('.message-assistant').filter({ hasText: saved.content })).toHaveCount(1)
    expect(python(`import sys
from app.memory.short_term_memory import ShortTermMemoryManager
assert ShortTermMemoryManager().get_history(sys.argv[2],user_id=sys.argv[1])==[]
print('no stale mirror restored')`, String(account.userId), String(session.id))).toBe('no stale mirror restored')
    await screenshot('history-expired-answer-retained.png')
    // Check captured server output without attaching private canaries or logs.
    for (const id of [agent, gateway]) {
      const result = spawnSync('docker', ['logs', '--since', logStart, id], { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
      expect(result.status, 'Read service stdout and stderr').toBe(0)
      const logs = result.stdout + result.stderr
      expect(logs.includes(privacyCanary), 'Provider body absent from service logs').toBe(false)
    }
    for (const entry of fs.readdirSync(testInfo.outputDir, { recursive: true, withFileTypes: true })) {
      if (!entry.isFile() || !/\.(json|txt|log)$/.test(entry.name)) continue
      const file = `${entry.parentPath ?? entry.path}/${entry.name}`
      expect(fs.readFileSync(file, 'utf8').includes(privacyCanary), 'Provider body absent from test artifacts').toBe(false)
    }
    await testInfo.attach('memory-outbox.json', { body: JSON.stringify({ sql_fault: true, answer_retained: true, restart: true, manual_retry: true, candidate_count: 1, payload_purged: true, confirmed: true, replay_idempotent: true, scheduled_history_expiry: true, active_history_retained: true, scheduled_completion_expiry: true, legacy_checkpoint_retained: true, expired_completion_fenced: true }), contentType: 'application/json' })
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
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM mneme.user WHERE id=${account.userId}`), { timeout: 90_000, intervals: [1000] }).toBe('0')
      expect(python(`import sys
from app.memory.session_history import count_user
assert count_user(sys.argv[1])==0
print('history cleared')`, String(account.userId))).toBe('history cleared')
    }
  }
})
