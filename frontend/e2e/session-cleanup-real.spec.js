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
user,*ids=sys.argv[1:]
print(json.dumps({'redis':session_persistence.count_sessions(ids),'manifest':session_store.cleanup_session_ids(user)}))`, entry.account.userId, ...entry.sessions))
  }
  async function waitDeleted(entry) {
    expect(String(entry.account.userId)).toMatch(/^\d+$/)
    await expect.poll(() => query(`SELECT status FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`),
      { timeout: 60000, intervals: [500, 1000, 2000] }).toBe('completed')
    expect(query(`SELECT COUNT(*) FROM user WHERE id=${entry.account.userId}; SELECT COUNT(*) FROM chat_session WHERE user_id=${entry.account.userId};`)).toBe('0\n0')
    expect(readback(entry)).toEqual({ redis: 0, manifest: [] })
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
      python(`import sys
from app.memory.session_store import session_store
from app.memory.session_persistence import session_persistence
user,first,missing=sys.argv[1:]
assert all(value.isascii() and value.isdecimal() for value in (user,first,missing))
assert session_persistence._ensure_connection()
session_store._save(user,{first:{'last_updated':'2000-01-01T00:00:00'}})
for value in (first,missing): session_persistence._redis.set('mneme:session:'+value,'isolated QA')
print('ok')`, account.userId, ...entry.sessions)
      expect(readback(entry)).toEqual({ redis: 2, manifest: [entry.sessions[0]] })
    }
    const [target, protectedUser] = accounts
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), protectedUser.account)
    // Use the protected tenant's real page after deleting the first account.
    await api(target.client, 'delete', '/profile/account')
    target.queued = true
    await waitDeleted(target)
    await page.context().addCookies(await other.storageState().then(state => state.cookies))
    expect(readback(protectedUser)).toEqual({ redis: 2, manifest: [protectedUser.sessions[0]] })
    expect(query(`SELECT COUNT(*) FROM chat_session WHERE user_id=${protectedUser.account.userId};`)).toBe('2')
    await page.goto('/chat')
    const toggle = page.getByRole('button', { name: '切换会话栏' })
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click()
    await expect(page.getByRole('button', { name: /打开对话：Session cleanup QA/ })).toHaveCount(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('protected-session-history.png'), fullPage: true, animations: 'disabled' })
    await testInfo.attach('session-cleanup.json', { body: JSON.stringify({ expired_and_missing_manifest: true, redis_readback_zero: true, mysql_readback_zero: true, protected_tenant_sessions: 2 }), contentType: 'application/json' })
  } finally {
    for (const entry of accounts) {
      if (!entry.queued) { await api(entry.client, 'delete', '/profile/account'); entry.queued = true }
      if (!entry.verified) await waitDeleted(entry)
    }
    await other.dispose()
  }
})
