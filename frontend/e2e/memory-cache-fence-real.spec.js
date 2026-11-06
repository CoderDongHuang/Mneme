import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('记忆缓存：实际查询迟到、跨实例失效、删除与另一账号页面隔离', async ({ page, playwright }, testInfo) => {
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
  const probe = mode => execFileSync('docker', ['exec', agent, 'python', '/app/scripts/check_memory_cache_fence.py', mode, ...accounts.map(account => String(account.userId))], { encoding: 'utf8', timeout: 75000 })
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    for (let index = 0; index < 2; index++) {
      const client = index === 1 ? page.request : await playwright.request.newContext({ baseURL: testInfo.project.use.baseURL || process.env.MNEME_E2E_BASE_URL })
      clients.push(client)
      const suffix = randomUUID().replaceAll('-', '')
      accounts.push(await api(client, 'post', '/auth/register', { username: `memorycache_${suffix.slice(0, 12)}`, password: `MemoryCache!${suffix}` }))
    }
    expect(probe('seed')).toContain('PASS: memory cache fence seed')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), accounts[1])
    await page.goto('/memory')
    const entry = () => page.getByRole('button', { name: /Memory cache QA/ })
    await expect(entry()).toHaveCount(1)
    await expect(entry()).toBeVisible()
    await shot('memory-cache-before.png')
    expect(probe('race')).toContain('PASS: memory cache fence race')
    await page.reload()
    await expect(entry()).toHaveCount(1)
    await expect(entry()).toBeVisible()
    const memories = (await api(page.request, 'get', '/workspace/memories')).memories
    expect(memories).toHaveLength(1)
    expect(memories[0].content).toBe('Memory cache QA: updated source evidence retained for the other account.')
    await shot('memory-cache-other-unaffected.png')
    await entry().click()
    const detail = page.getByRole('complementary', { name: '记忆详情', exact: true })
    await expect(detail.getByRole('textbox', { name: '内容', exact: true })).toHaveValue(memories[0].content)
    await shot('memory-cache-detail.png')
  } finally {
    const cleanup = await Promise.allSettled(accounts.map((_, index) => api(clients[index], 'delete', '/profile/account')))
    try {
      for (const result of cleanup) expect(result.status, '正式账号清理').toBe('fulfilled')
      if (accounts.length === 2) {
        const readback = 'import sys; from app.knowledge.generations import generation_store as g; from app.memory.memory_store import memory_store as m; from app.memory.cache_revision import memory_cache_revision as r; print(all(g.snapshot(u).get("deleted") and m.count_user_memories(u) == 0 and not r._redis.exists(r._key(u)) for u in sys.argv[1:]))'
        await expect.poll(() => execFileSync('docker', ['exec', agent, 'python', '-c', readback, ...accounts.map(account => String(account.userId))], { encoding: 'utf8', timeout: 15000 }).trim(), { timeout: 60000 }).toBe('True')
        expect(probe('verify')).toContain('PASS: memory cache fence verify')
      }
    } finally {
      await Promise.all(clients.filter(client => client !== page.request).map(client => client.dispose()))
    }
  }
})
