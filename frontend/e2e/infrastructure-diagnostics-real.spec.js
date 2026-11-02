import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent、MySQL、Redis、对象存储和 Mailpit')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实业务诊断、本人邮件、权限及清理在桌面和移动端成立', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180000)
  const container = service => execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  const gateway = container('java-gateway'), mysql = container('mysql'), agent = container('python-agent')
  for (const id of [gateway, mysql, agent]) expect(id).toMatch(/^[a-f0-9]+$/)
  const env = JSON.parse(execFileSync('docker', ['inspect', '--format', '{{json .Config.Env}}', gateway], { encoding: 'utf8' }))
  const adminToken = env.find(value => value.startsWith('ADMIN_API_TOKEN='))?.slice('ADMIN_API_TOKEN='.length)
  expect(Boolean(adminToken && adminToken.length >= 32)).toBe(true)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const inbox = await playwright.request.newContext({ baseURL: process.env.MNEME_MAILPIT_URL || 'http://127.0.0.1:8025' })
  const suffix = randomUUID().replaceAll('-', ''), username = `diagqa_${suffix.slice(0, 12)}`
  const email = `${username}@example.test`, ownMailIds = new Set(), results = {}
  let account, diagnosticRequests = 0
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/v1/admin/operations/check/')) diagnosticRequests++ })
  async function api(method, path, data, headers = {}) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, { data, headers })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  async function messages(subject) {
    const response = await inbox.get('/api/v1/search', { params: { query: `to:${email}`, limit: 100 } })
    expect(response.ok()).toBe(true)
    const own = ((await response.json()).messages || []).filter(item => item.To?.some(recipient => recipient.Address === email))
    for (const item of own) ownMailIds.add(item.ID)
    return own.filter(item => item.Subject.includes(subject))
  }
  const section = () => page.getByRole('region', { name: '基础设施业务诊断', exact: true })
  async function check(key, label) {
    const response = page.waitForResponse(value => new URL(value.url()).pathname === `/api/v1/admin/operations/check/${key}`)
    await section().getByRole('button', { name: label, exact: true }).click()
    const reply = await response
    expect(reply.status()).toBe(200)
    const data = (await reply.json()).data
    expect(['present', 'missing']).toContain(data.configuration)
    expect(typeof data.checked_at).toBe('string')
    results[key] = data
    return data
  }
  try {
    expect((await page.request.post('http://127.0.0.1:8001/health/storage/check')).status()).toBe(401)
    account = await api('post', '/auth/register', { username, password: `Diagnostic!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    for (const key of ['mysql', 'redis', 'qdrant', 'object_storage', 'backup_keys', 'smtp']) {
      const denied = await page.request.post('/api/v1/admin/operations/check/' + key, { headers: { 'X-Admin-Token': adminToken } })
      expect(denied.status()).toBe(403)
    }
    // Only promote this synthetic account; email ownership follows the real flow.
    expect(sql(`UPDATE user SET role='admin' WHERE id=${account.userId} AND username='${username}'; SELECT role FROM user WHERE id=${account.userId}`)).toBe('admin')
    const unverified = await api('post', '/admin/operations/check/smtp', undefined, { 'X-Admin-Token': adminToken })
    expect(unverified.code).toBe('VERIFIED_EMAIL_REQUIRED')
    await api('patch', '/profile', { email })
    await api('post', '/profile/email-verification/request', { email })
    let verification
    await expect.poll(async () => { verification = await messages('邮箱验证'); return verification.length }).toBe(1)
    const mail = await inbox.get(`/api/v1/message/${verification[0].ID}`)
    const token = (await mail.json()).Text?.match(/\b[0-9a-f]{64}\b/)?.[0]
    expect(Boolean(token)).toBe(true)
    await api('post', '/profile/email-verification/confirm', { token })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.goto('/operations')
    await page.getByLabel('管理员凭证', { exact: true }).fill(adminToken)
    await page.getByRole('button', { name: '验证权限', exact: true }).click()
    await expect(section()).toBeVisible()
    expect(diagnosticRequests).toBe(0)
    for (const [key, label] of [['mysql', 'MySQL'], ['redis', 'Redis'], ['qdrant', 'Qdrant'], ['object_storage', '对象存储']]) {
      const data = await check(key, `检查 ${label}`)
      expect(data.configuration).toBe('present')
      expect(data.operation).toBe('passed')
      expect(data.cleanup).toBe('passed')
      expect(data.code).toBe('OK')
    }
    const keys = await check('backup_keys', '检查 备份密钥')
    // An absent host executor/key configuration is visible, never a fabricated pass.
    expect(['OK', 'NOT_CONFIGURED', 'CONNECTION_FAILED']).toContain(keys.code)
    if (keys.code === 'OK') expect(keys.operation).toBe('passed')
    else expect(keys.operation).toBe('not_run')
    const sent = await check('smtp', '发送测试邮件')
    expect(sent.code).toBe('SMTP_ACCEPTED')
    expect(sent.connection).toBe('passed')
    expect(sent.operation).toBe('passed')
    await expect.poll(async () => (await messages('服务诊断')).length).toBe(1)
    expect((await check('smtp', '发送测试邮件')).code).toBe('RATE_LIMITED')
    expect((await messages('服务诊断')).length).toBe(1)
    expect(sql('SELECT COUNT(*) FROM operations_diagnostic_probe')).toBe('0')
    const zeroVectors = execFileSync('docker', ['exec', agent, 'python', '-c', "from app.knowledge.vector_store import vector_store; print(sum(c.name.startswith('mneme_diagnostic_') for v in vector_store.clients for c in v.raw.get_collections().collections))"], { encoding: 'utf8', timeout: 30000 }).trim()
    expect(zeroVectors).toBe('0')
    const zeroRedis = execFileSync('docker', ['exec', agent, 'python', '-c', "from app.memory.session_persistence import session_persistence; print(sum(1 for _ in session_persistence._redis.scan_iter(match='mneme:diagnostics:probe:*')))"], { encoding: 'utf8', timeout: 15000 }).trim()
    expect(zeroRedis).toBe('0')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await section().scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('infrastructure-diagnostics.png'), fullPage: false, animations: 'disabled' })
    await page.getByRole('button', { name: '锁定', exact: true }).click()
    await expect(section()).toHaveCount(0)
    expect(await page.evaluate(secret => ![...Object.values(localStorage), ...Object.values(sessionStorage)].some(value => value.includes(secret)), adminToken)).toBe(true)
    await testInfo.attach('diagnostics.json', { body: JSON.stringify({ results, sql_probe_rows: 0, redis_probe_keys: 0, qdrant_probe_collections: 0, verified_self_email_received: true }), contentType: 'application/json' })
  } finally {
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 30000, intervals: [1000] }).toBe('0')
    }
    if (ownMailIds.size) expect((await inbox.delete('/api/v1/messages', { data: { IDs: [...ownMailIds] } })).ok()).toBe(true)
    await inbox.dispose()
  }
})
