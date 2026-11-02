import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('账号删除隔离迟到 Trace 与隐私写入，实际部署存储并发和最终读回', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180000); page.setDefaultTimeout(15000)
  const agent = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(agent).toMatch(/^[a-f0-9]+$/)
  const accounts = [], clients = []
  async function api(client, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await client[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after']); expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const probe = mode => {
    const ids = accounts.map(account => String(account.userId))
    ids.forEach(id => expect(id).toMatch(/^\d+$/))
    return execFileSync('docker', ['exec', agent, 'python', '/app/scripts/check_trace_privacy_fence.py', mode, ...ids], { encoding: 'utf8', timeout: 60000 })
  }
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    for (let index = 0; index < 3; index++) {
      const client = index === 2 ? page.request : await playwright.request.newContext({ baseURL: testInfo.project.use.baseURL || process.env.MNEME_E2E_BASE_URL })
      clients.push(client)
      const suffix = randomUUID().replaceAll('-', '')
      accounts.push(await api(client, 'post', '/auth/register', { username: `tracefence_${suffix.slice(0, 12)}`, password: `TraceFence!${suffix}` }))
    }
    expect(probe('seed')).toContain('PASS: trace/privacy seed')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), accounts[2])
    await page.goto('/privacy')
    await expect(page.getByRole('checkbox', { name: '允许外部模型处理', exact: true })).toBeChecked()
    await expect(page.getByRole('spinbutton', { name: 'Trace 保留天数', exact: true })).toHaveValue('1')
    await shot('trace-fence-before.png')
    expect(probe('race')).toContain('PASS: trace/privacy race')
    // The two concurrent erasures must leave this independent account intact.
    await page.reload()
    await expect(page.getByRole('checkbox', { name: '允许外部模型处理', exact: true })).toBeChecked()
    expect((await api(page.request, 'get', '/privacy')).trace_days).toBe(1)
    await shot('trace-fence-other-unaffected.png')
  } finally {
    const cleanup = await Promise.allSettled(accounts.map((_, index) => api(clients[index], 'delete', '/profile/account')))
    try {
      for (const result of cleanup) expect(result.status, '正式账号清理').toBe('fulfilled')
      if (accounts.length === 3) {
        // DELETE accepts a durable background task; acceptance is not completion.
        const readback = 'import sys; from app.knowledge.generations import generation_store as g; from app.agents.trace_store import agent_trace_store as t; from app.core.privacy import privacy_store as p; print(all(g.snapshot(u).get("deleted") and t.count_user(u) == p.count_user(u) == 0 for u in sys.argv[1:]))'
        await expect.poll(() => execFileSync('docker', ['exec', agent, 'python', '-c', readback, ...accounts.map(account => String(account.userId))], { encoding: 'utf8', timeout: 15000 }).trim(), { timeout: 60000 }).toBe('True')
        expect(probe('verify')).toContain('PASS: trace/privacy verify')
      }
    } finally {
      await Promise.all(clients.filter(client => client !== page.request).map(client => client.dispose()))
    }
  }
})
