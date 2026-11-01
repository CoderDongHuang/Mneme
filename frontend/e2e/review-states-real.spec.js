import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('复习卡和计划独立恢复，真实创建与评分保留回执且刷新可读', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  let account, failCards = true, failPlans = true, ratingWrites = 0, planWrites = 0
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  async function clickRequest(button, method, path) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1' + path && response.request().method() === method)
      await button.click()
      const response = await pending
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      return
    }
  }
  const fail = route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '读取服务暂不可用' }) })
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false })
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api('post', '/auth/register', { username: `reviewstate_${suffix.slice(0, 10)}`, password: `Review!${suffix}` })
    await api('post', '/workspace/plans', { title: '初始真实计划', goal: '独立读取与评分回归', cards: [
      { prompt: '第一张真实问题', answer: '第一张真实答案' }, { prompt: '第二张真实问题', answer: '第二张真实答案' },
    ] })
    const initial = await api('get', '/workspace/reviews')
    expect(initial).toHaveLength(2)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/workspace/reviews', route => route.request().method() === 'GET' && failCards ? fail(route) : route.continue())
    await page.route('**/api/v1/workspace/plans', route => route.request().method() === 'GET' && failPlans ? fail(route) : route.continue())
    page.on('response', response => {
      if (response.request().method() !== 'POST' || !response.ok()) return
      const path = new URL(response.url()).pathname
      if (/\/workspace\/reviews\/\d+$/.test(path)) ratingWrites++
      if (path === '/api/v1/workspace/plans') planWrites++
    })
    await page.goto('/review')
    const cards = page.getByRole('region', { name: '复习卡片', exact: true })
    const plans = page.getByRole('region', { name: '我的计划', exact: true })
    await expect(cards.getByText('复习卡加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(plans.getByText('学习计划加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByText('—', { exact: true })).toHaveCount(3)
    for (const text of ['今天的复习已就绪', '还没有计划。', '暂无记录', '复习日历']) await expect(page.getByText(text, { exact: true })).toHaveCount(0)
    await shot('review-unavailable.png')
    failCards = false
    await clickRequest(cards.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/reviews')
    await expect(cards.getByRole('button', { name: '查看答案', exact: true })).toBeVisible()
    const currentPrompt = await cards.getByRole('heading', { level: 2 }).innerText()
    const current = initial.find(item => item.prompt === currentPrompt)
    expect(current).toBeTruthy()
    await cards.getByRole('button', { name: '查看答案', exact: true }).click()
    await expect(cards.getByText(current.answer, { exact: true })).toBeVisible()
    failPlans = false
    await clickRequest(plans.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/plans')
    await expect(plans.getByText('初始真实计划', { exact: true })).toBeVisible()
    await expect(cards.getByText(current.answer, { exact: true })).toBeVisible()

    await page.getByRole('button', { name: '制定计划', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '制定学习计划', exact: true })
    await dialog.getByRole('textbox', { name: '计划名称', exact: true }).fill('刷新后可见的真实计划')
    await dialog.getByRole('textbox', { name: '学习目标', exact: true }).fill('保存回执不被读取失败抹去')
    await dialog.getByRole('textbox', { name: '问题', exact: true }).fill('新建真实问题')
    await dialog.getByRole('textbox', { name: '参考答案', exact: true }).fill('新建真实答案')
    failCards = true; failPlans = true
    await clickRequest(dialog.getByRole('button', { name: '创建计划', exact: true }), 'POST', '/workspace/plans')
    await expect(page.getByText('计划已创建，复习卡使用你填写的真实答案', { exact: true })).toBeVisible()
    await expect(cards.getByText('已有复习卡可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(plans.getByText('已有计划可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(cards.getByText(current.answer, { exact: true })).toBeVisible()
    expect((await api('get', '/workspace/plans')).some(item => item.title === '刷新后可见的真实计划')).toBe(true)
    await shot('review-saved-reads-unavailable.png')
    failPlans = false
    await clickRequest(plans.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/plans')
    await expect(plans.getByText('刷新后可见的真实计划', { exact: true })).toBeVisible()
    await expect(cards.getByText(current.answer, { exact: true })).toBeVisible()
    await clickRequest(cards.getByRole('button', { name: '基本掌握', exact: true }), 'POST', `/workspace/reviews/${current.id}`)
    await expect(page.getByText(/^评分已保存，下次复习：/)).toBeVisible()
    await expect(cards.getByText(current.answer, { exact: true })).toHaveCount(0)
    const saved = (await api('get', '/workspace/reviews')).find(item => item.id === current.id)
    expect(saved.review_count).toBe(1)
    expect(new Date(saved.due_at).getTime()).toBeGreaterThan(Date.now())
    failCards = false
    await clickRequest(cards.getByRole('button', { name: '重试 / Retry', exact: true }), 'GET', '/workspace/reviews')
    await expect(cards.getByRole('button', { name: '查看答案', exact: true })).toBeVisible()
    await expect(cards.getByText('复习卡加载失败：读取服务暂不可用', { exact: true })).toHaveCount(0)
    await shot('review-recovered.png')
    expect(ratingWrites).toBe(1)
    expect(planWrites).toBe(1)
    await page.reload()
    await expect(plans.getByText('刷新后可见的真实计划', { exact: true })).toBeVisible()
    await expect(cards.getByRole('heading', { name: currentPrompt, exact: true })).toHaveCount(0)
    expect((await api('get', '/workspace/reviews')).find(item => item.id === current.id).review_count).toBe(1)
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
