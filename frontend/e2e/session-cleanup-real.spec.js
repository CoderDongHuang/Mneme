import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('账号删除覆盖过期及缺失元数据会话，真实 Redis 与 MySQL 读回且隔离其他用户', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180000)
  function container(service) {
    const ids = execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
    expect(ids).toHaveLength(1)
    return ids[0]
  }
  const agent = container('python-agent'), mysql = container('mysql')
  function sessionProbe(mode, ...users) {
    return execFileSync('docker', ['exec', agent, 'python', 'scripts/check_session_memory_fence.py', mode, ...users.map(String)],
      { encoding: 'utf8', timeout: 90000 }).trim().split('\n').at(-1)
  }
  function python(code, ...args) {
    return execFileSync('docker', ['exec', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 20000 }).trim().split('\n').at(-1)
  }
  function query(sql) {
    return execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot mneme -N'], { input: sql, encoding: 'utf8', timeout: 15000 }).trim()
  }
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  const accounts = []
  async function api(client, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await client[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.ok(), `${method} ${path}: ${response.status()}`).toBe(true)
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  function readback(entry) {
    return JSON.parse(python(`import json,sys
from app.memory.session_store import session_store
from app.memory.session_persistence import session_persistence
import app.memory.reflection_scheduler as reflection
from app.knowledge.generations import generation_store
user,raw_entries,*ids=sys.argv[1:]
scheduler=reflection.ReflectionScheduler(); client=scheduler._redis
exact=[scheduler._counter_key(user),scheduler._job_key(user),scheduler._lease_key(user),scheduler._lease_state_key(user)]
print(json.dumps({'redis':session_persistence.count_sessions(ids,user_id=user),'manifest':session_store.cleanup_session_ids(user),
 'reflection_keys':client.exists(*exact)+len(list(scheduler._delivery_keys(user))),
 'reflection_receipts':sum(len(bucket) for bucket in generation_store.snapshot(user).get('reflection_deliveries',{}).values()),
 'reflection_entries':sum(len(batch) for batch in scheduler._user_queue_batches(user)),
 'reflection_pending':sum(len(client.xpending_range(reflection._QUEUE_KEY,reflection._QUEUE_GROUP,identifier,identifier,1)) for identifier in json.loads(raw_entries))}))`, entry.account.userId, JSON.stringify(entry.reflectionIds), ...entry.sessions))
  }
  async function waitDeleted(entry) {
    expect(String(entry.account.userId)).toMatch(/^\d+$/)
    await expect.poll(() => query(`SELECT status FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`),
      { timeout: 60000, intervals: [500, 1000, 2000] }).toBe('completed')
    expect(query(`SELECT COUNT(*) FROM user WHERE id=${entry.account.userId}; SELECT COUNT(*) FROM chat_session WHERE user_id=${entry.account.userId};`)).toBe('0\n0')
    expect(readback(entry)).toEqual({ redis: 0, manifest: [], reflection_keys: 0, reflection_receipts: 0, reflection_entries: 0, reflection_pending: 0 })
    expect(sessionProbe('verify', entry.account.userId)).toContain('PASS: session memory fence verify')
    expect(python(`import sys
from app.knowledge.generations import generation_store,StaleGeneration
from app.memory.reflection_scheduler import ReflectionScheduler
user=sys.argv[1]; scheduler=ReflectionScheduler()
assert generation_store.snapshot(user)['deleted']
try: scheduler.record_session(user,'late-session','late-turn')
except StaleGeneration: pass
else: raise AssertionError('Deleted reflection counter was resurrected')
assert not scheduler.check_and_trigger(user)
assert not scheduler._claim_shared(user,'qa-job','late-owner')
scheduler._run_queued_reflection('1-0',{'user_id':user,'claimed_count':'1'})
assert not scheduler._complete_shared(user,1,'qa-job','qa-owner','1-0')
from app.memory.session_store import SessionStore
from pathlib import Path
store=SessionStore()
for operation in (lambda:store.register_session(user,'late'),lambda:store._save(user,{'late':{}}),
                  lambda:store.update_title(user,'late','late'),lambda:store.increment_message_count(user,'late'),
                  lambda:store.delete_session(user,'late')):
    try: operation()
    except StaleGeneration: pass
    else: raise AssertionError('Deleted session manifest was mutated')
assert store.get_sessions(user)==[] and store.get_session_count(user)==0
assert not Path(store._get_file_path(user)).exists()
print('late-reflection-rejected')`, entry.account.userId)).toBe('late-reflection-rejected')
    expect(readback(entry)).toEqual({ redis: 0, manifest: [], reflection_keys: 0, reflection_receipts: 0, reflection_entries: 0, reflection_pending: 0 })
    entry.verified = true
  }
  try {
    for (const client of [page.request, other]) {
      const suffix = randomUUID().replaceAll('-', '')
      const account = await api(client, 'post', '/auth/register', { username: `sessionqa_${suffix.slice(0, 12)}`, password: `SessionQA!${suffix}` })
      const entry = { client, account, sessions: [] }
      accounts.push(entry)
      for (let i = 0; i < 2; i++) {
        const session = await api(client, 'post', '/sessions', { title: `Session cleanup QA ${i}` })
        expect(String(session.id)).toMatch(/^\d+$/)
        entry.sessions.push(String(session.id))
      }
      // Reproduce stale metadata and an existing canonical session absent from it.
      // This writes only IDs created by this test; never scans or edits other keys.
      entry.reflectionIds = JSON.parse(python(`import json,sys
from app.memory.session_store import session_store
from app.memory.session_persistence import session_persistence
import app.memory.reflection_scheduler as reflection
user,first,missing=sys.argv[1:]
assert all(value.isascii() and value.isdecimal() for value in (user,first,missing))
assert session_persistence._ensure_connection()
session_store._save(user,{first:{'last_updated':'2000-01-01T00:00:00'}})
for value in (first,missing): session_persistence._redis.set('mneme:session:'+value,'isolated QA')
scheduler=reflection.ReflectionScheduler(); client=scheduler._redis
assert scheduler.record_session(user,first,'qa-turn')==1
# Include a pre-upgrade marker as well as the new durable SQL receipt.
client.set(scheduler._delivery_key(user,first,'legacy-qa-turn'),'1',ex=600)
scheduler._ensure_queue()
client.set(scheduler._job_key(user),'qa-job')
client.set(scheduler._lease_key(user),'qa-owner',ex=600)
client.set(scheduler._lease_state_key(user),'active',ex=600)
entries=[]
for fields in ({'user_id':user,'claimed_count':'1','job_token':'qa-job'},
               {'user_id':user,'claimed_count':'1'}):
 identifier=client.xadd(reflection._QUEUE_KEY,fields); entries.append(identifier)
 client.xclaim(reflection._QUEUE_KEY,reflection._QUEUE_GROUP,'qa-cleanup',0,[identifier],force=True)
print(json.dumps(entries))`, account.userId, ...entry.sessions))
      expect(readback(entry)).toEqual({ redis: 2, manifest: [entry.sessions[0]], reflection_keys: 5, reflection_receipts: 1, reflection_entries: 2, reflection_pending: 2 })
    }
    const [target, protectedUser] = accounts
    expect(sessionProbe('seed', target.account.userId, protectedUser.account.userId)).toContain('PASS: session memory fence seed')
    expect(sessionProbe('race', target.account.userId, protectedUser.account.userId)).toContain('PASS: session memory fence race')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), protectedUser.account)
    // Use the protected tenant's real page after deleting the first account.
    await api(target.client, 'delete', '/profile/account')
    target.queued = true
    await waitDeleted(target)
    await page.context().addCookies(await other.storageState().then(state => state.cookies))
    expect(readback(protectedUser)).toEqual({ redis: 2, manifest: [protectedUser.sessions[0]], reflection_keys: 5, reflection_receipts: 1, reflection_entries: 2, reflection_pending: 2 })
    expect(query(`SELECT COUNT(*) FROM chat_session WHERE user_id=${protectedUser.account.userId};`)).toBe('2')
    await page.goto('/chat')
    const toggle = page.getByRole('button', { name: '切换会话栏' })
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click()
    await expect(page.getByRole('button', { name: /打开对话：Session cleanup QA/ })).toHaveCount(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('protected-session-history.png'), fullPage: true, animations: 'disabled' })
    await testInfo.attach('session-cleanup.json', { body: JSON.stringify({ expired_and_missing_manifest: true, redis_readback_zero: true, mysql_readback_zero: true, reflection_keys_stream_and_pending_zero: true, durable_late_reflection_rejected: true, durable_late_manifest_rejected: true, scoped_cache_late_write_rejected: true, stale_summary_discarded: true, scoped_orphan_cache_erased: true, protected_tenant_sessions: 2 }), contentType: 'application/json' })
  } finally {
    for (const entry of accounts) {
      if (!entry.queued) { await api(entry.client, 'delete', '/profile/account'); entry.queued = true }
      if (!entry.verified) await waitDeleted(entry)
    }
    await other.dispose()
  }
})
