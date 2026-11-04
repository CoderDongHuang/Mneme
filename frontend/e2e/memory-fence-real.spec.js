import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('长期记忆和版本删除围栏：真实存储竞态、另一账号隔离与新进程读回', async ({ page, playwright }, testInfo) => {
  test.setTimeout(180000); page.setDefaultTimeout(15000)
  const agent = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(agent).toMatch(/^[a-f0-9]+$/)
  const accounts = [], clients = []
  async function readWithRecovery(action, path, retry) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1' + path && response.request().method() === 'GET')
      await (attempt ? retry() : action())
      const response = await pending
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.status(), `GET ${path}`).toBe(200)
      return
    }
  }
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
    return execFileSync('docker', ['exec', agent, 'python', '/app/scripts/check_memory_deletion_fence.py', mode, ...ids], { encoding: 'utf8', timeout: 60000 })
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
      accounts.push(await api(client, 'post', '/auth/register', { username: `memoryfence_${suffix.slice(0, 12)}`, password: `MemoryFence!${suffix}` }))
    }
    expect(probe('seed')).toContain('PASS: memory fence seed')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), accounts[2])
    await readWithRecovery(() => page.goto('/memory'), '/workspace/memories', () => page.getByRole('button', { name: '刷新记忆', exact: true }).click())
    const entry = () => page.getByRole('button', { name: /Memory fence QA/ })
    await expect(entry()).toHaveCount(1)
    await expect(entry()).toBeVisible()
    expect((await api(page.request, 'get', '/workspace/memories')).memories).toHaveLength(1)
    await shot('memory-fence-before.png')
    expect(probe('race')).toContain('PASS: memory fence race')
    // The independent account must retain its real memory and all versions.
    await readWithRecovery(() => page.reload(), '/workspace/memories', () => page.getByRole('button', { name: '刷新记忆', exact: true }).click())
    await expect(entry()).toHaveCount(1)
    await expect(entry()).toBeVisible()
    const memories = (await api(page.request, 'get', '/workspace/memories')).memories
    expect(memories).toHaveLength(1)
    expect(memories[0].topic).toBe('Memory fence QA updated')
    expect(memories[0].importance).toBe(0.9)
    const versions = (await api(page.request, 'get', `/workspace/memories/${memories[0].id}/versions`)).versions
    expect(versions).toHaveLength(35)
    expect(new Set(versions.map(item => item.version)).size).toBe(35)
    await shot('memory-fence-other-unaffected.png')
    const detail = page.getByRole(testInfo.project.name === '移动端' ? 'dialog' : 'complementary', { name: '记忆详情', exact: true })
    let throttleVersions = true
    const versionsPath = `/workspace/memories/${memories[0].id}/versions`
    await page.route('**/api/v1' + versionsPath, route => {
      if (route.request().method() === 'GET' && throttleVersions) {
        throttleVersions = false
        return route.fulfill({ status: 429, headers: { 'Retry-After': '1' }, contentType: 'application/json',
          body: JSON.stringify({ code: 429, message: '请求过于频繁，请稍后再试' }) })
      }
      return route.continue()
    })
    await readWithRecovery(async () => {
      await entry().click()
      await detail.locator('summary').filter({ hasText: /^历史版本/ }).click()
    }, versionsPath, () => detail.getByRole('region', { name: '记忆历史版本' }).getByRole('button', { name: '重试 / Retry', exact: true }).click())
    await expect(detail.getByRole('textbox', { name: '内容', exact: true })).toHaveValue('Memory fence QA: inspect source evidence before taking study notes.')
    await expect(detail.getByRole('button', { name: '恢复此版本', exact: true })).toHaveCount(35)
    await shot('memory-fence-version-history.png')
  } finally {
    const cleanup = await Promise.allSettled(accounts.map((_, index) => api(clients[index], 'delete', '/profile/account')))
    try {
      for (const result of cleanup) expect(result.status, '正式账号清理').toBe('fulfilled')
      if (accounts.length === 3) {
        // DELETE accepts a durable background task; acceptance is not completion.
        const readback = 'import sys; from app.knowledge.generations import generation_store as g; from app.memory.memory_store import memory_store as m; from app.memory.version_store import memory_version_store as v; print(all(g.snapshot(u).get("deleted") and m.count_user_memories(u) == v.count_user(u) == 0 for u in sys.argv[1:]))'
        await expect.poll(() => execFileSync('docker', ['exec', agent, 'python', '-c', readback, ...accounts.map(account => String(account.userId))], { encoding: 'utf8', timeout: 15000 }).trim(), { timeout: 60000 }).toBe('True')
        expect(probe('verify')).toContain('PASS: memory fence verify')
      }
    } finally {
      await Promise.all(clients.filter(client => client !== page.request).map(client => client.dispose()))
    }
  }
})
