import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway 和记忆存储')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('记忆读取故障不伪装为空数据，版本恢复与保存使用真实服务', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  let account, failItems = true, failPending = true, failVersions = true, writes = 0
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
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
  const fail = route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '记忆服务暂不可用' }) })
  async function browserAction(button, method, path, additionalPaths = []) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const responsePromise = Promise.all([path, ...additionalPaths].map(item => page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/v1' + item && response.request().method() === method)))
      await button.click()
      const responses = await responsePromise
      const limited = responses.filter(response => response.status() === 429)
      for (const response of responses) expect([200, 429]).toContain(response.status())
      if (limited.length && attempt < 2) {
        const seconds = Math.max(...limited.map(response => Number(response.headers()['retry-after'])))
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      for (const response of responses) expect(response.status(), `${method} ${path}`).toBe(200)
      return
    }
  }
  const metric = name => page.locator('.reference-metrics > div').filter({ has: page.getByText(name, { exact: true }) }).locator('strong')
  const screenshot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    const state = () => page.evaluate(() => ({ width: innerWidth, height: innerHeight,
      details: [...document.querySelectorAll('details')].map(item => ({ open: item.open, summary: item.querySelector('summary')?.textContent })) }))
    const before = await state()
    // Full-page capture temporarily resizes Chromium to 1x1 on some Windows
    // builds, switching the responsive detail pane to a drawer and remounting it.
    // Capture the actual user viewport so screenshots do not mutate the layout.
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false })
    const after = await state()
    await testInfo.attach(name + '.layout', { body: JSON.stringify({ before, after }), contentType: 'application/json' })
    expect(after.details).toEqual(before.details)
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api('post', '/auth/register', { username: `memorystate_${suffix.slice(0, 10)}`, password: `MemoryState!${suffix}` })
    await api('post', '/memory/write', { category: 'preference', content: '先核对引用原文，再整理学习笔记。' })
    await api('post', '/memory/write', { category: 'weak_point', topic: '记忆状态回归乙', content: '向量检索距离和概率分布还需要练习。' })
    const seeded = await api('get', '/workspace/memories')
    expect(seeded.memories).toHaveLength(2)
    await api('patch', `/workspace/memories/${seeded.memories.find(item => item.category === 'preference').id}`, { topic: '记忆状态回归甲' })
    const original = await api('get', '/workspace/memories')
    expect(original.memories).toHaveLength(2)
    const entry = original.memories.find(item => item.topic === '记忆状态回归甲')
    const history = await api('get', `/workspace/memories/${entry.id}/versions`)
    expect(history.versions.length).toBeGreaterThan(0)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/workspace/memories', route => route.request().method() === 'GET' && failItems ? fail(route) : route.continue())
    await page.route('**/api/v1/memory/pending', route => route.request().method() === 'GET' && failPending ? fail(route) : route.continue())
    await page.route('**/api/v1/workspace/memories/*/versions', route => failVersions ? fail(route) : route.continue())
    page.on('response', response => { if (response.request().method() === 'PATCH' && response.ok()) writes++ })
    await page.goto('/memory')
    const search = page.getByRole('textbox', { name: '搜索记忆', exact: true })
    const searchBox = await search.boundingBox()
    expect(searchBox.width).toBeGreaterThanOrEqual(testInfo.project.name === '移动端' ? 250 : 120)
    await search.fill('搜索回归')
    await expect(search).toHaveValue('搜索回归')
    await search.clear()
    await expect(page.getByText('记忆列表加载失败，请重试。', { exact: true })).toBeVisible()
    for (const name of ['总记忆数', '待确认', '已掌握', '需巩固']) await expect(metric(name)).toHaveText('—')
    await expect(page.getByText('暂无符合条件的记忆', { exact: true })).toHaveCount(0)
    await screenshot('memory-unavailable.png')
    failItems = false
    await browserAction(page.getByRole('button', { name: '刷新记忆', exact: true }), 'GET', '/workspace/memories')
    await expect(page.getByRole('button', { name: /记忆状态回归甲/ })).toBeVisible()
    await expect(metric('总记忆数')).toHaveText('2')
    await expect(metric('待确认')).toHaveText('—')
    await page.getByRole('button', { name: /记忆状态回归甲/ }).click()
    const detail = page.getByRole(testInfo.project.name === '移动端' ? 'dialog' : 'complementary', { name: '记忆详情', exact: true })
    await detail.getByRole('textbox', { name: '内容', exact: true }).fill('已修改的学习记忆内容')
    await detail.getByRole('textbox', { name: '标签（以逗号分隔）', exact: true }).fill('版本回归, 学习')
    await detail.getByText('历史版本', { exact: true }).click()
    await expect(detail.getByText('记忆版本加载失败，请重试。', { exact: true })).toBeVisible()
    await expect(detail.getByText('暂无历史版本。', { exact: true })).toHaveCount(0)
    await screenshot('memory-version-unavailable.png')
    failVersions = false
    await browserAction(detail.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', `/workspace/memories/${entry.id}/versions`)
    await expect(detail.getByRole('button', { name: '恢复此版本', exact: true })).toHaveCount(history.versions.length)
    failVersions = true
    await browserAction(detail.getByRole('button', { name: '保存修改', exact: true }), 'PATCH', `/workspace/memories/${entry.id}`)
    await expect(detail.getByText('记忆已保存，检索缓存已更新', { exact: true })).toBeVisible()
    await expect(detail.getByText('记忆版本加载失败，请重试。', { exact: true })).toBeVisible()
    expect((await api('get', '/workspace/memories')).memories.find(item => item.id === entry.id).content).toBe('已修改的学习记忆内容')
    const savedHistory = await api('get', `/workspace/memories/${entry.id}/versions`)
    expect(savedHistory.versions.length).toBeGreaterThan(history.versions.length)
    await screenshot('memory-saved-version-refresh-failed.png')
    failVersions = false
    await browserAction(detail.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', `/workspace/memories/${entry.id}/versions`)
    await expect(detail.getByRole('button', { name: '恢复此版本', exact: true })).toHaveCount(savedHistory.versions.length)
    const prior = detail.getByRole('listitem').filter({ has: page.getByText('先核对引用原文，再整理学习笔记。', { exact: true }) }).first()
    await browserAction(prior.getByRole('button', { name: '恢复此版本', exact: true }), 'POST', `/workspace/memories/${entry.id}/restore`)
    await expect(detail.getByText('历史版本已恢复', { exact: true })).toBeVisible()
    await expect(detail.getByRole('textbox', { name: '内容', exact: true })).toHaveValue('先核对引用原文，再整理学习笔记。')
    await expect(detail.getByRole('textbox', { name: '标签（以逗号分隔）', exact: true })).toHaveValue('')
    expect((await api('get', '/workspace/memories')).memories.find(item => item.id === entry.id).content).toBe('先核对引用原文，再整理学习笔记。')
    await detail.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    failItems = true; failPending = false
    await browserAction(page.getByRole('button', { name: '刷新记忆', exact: true }), 'GET', '/memory/pending')
    await expect(page.getByText('已有记忆记录可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /记忆状态回归甲/ })).toBeVisible()
    await expect(metric('待确认')).toHaveText('0')
    await screenshot('memory-stale-list.png')
    failItems = false
    await browserAction(page.getByRole('button', { name: '刷新记忆', exact: true }), 'GET', '/workspace/memories', ['/memory/pending'])
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(writes).toBe(1)
    await screenshot('memory-recovered.png')
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
