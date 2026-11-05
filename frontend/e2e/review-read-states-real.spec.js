import { expect, request, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('复习独立读取与真实提交后损坏回执：核对只读、评分和计划不重复写入', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(20000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  const username = `reviewread_${suffix.slice(0, 12)}`, password = `ReviewRead!${suffix}`
  let account, cleanup, badCards = true, badPlans = true, cardGets = 0, planGets = 0, ratings = 0, creates = 0
  async function api(context, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await context[method]('/api/v1' + path, { data, timeout: 45000 })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const cards = page.getByRole('region', { name: '复习卡片', exact: true })
  const plans = page.getByRole('region', { name: '我的计划', exact: true })
  try {
    account = await api(page.request, 'post', '/auth/register', { username, password })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
    await api(cleanup, 'post', '/workspace/plans', { title: '已保存的复习计划', goal: '独立读取核对', cards: [{ prompt: '真实复习问题', answer: '真实复习答案' }] })
    const [card] = await api(cleanup, 'get', '/workspace/reviews')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/notifications/stream', route => route.fulfill({ contentType: 'text/event-stream', body: ': isolated\n\n' }))
    await page.route('**/api/v1/workspace/reviews', async route => {
      cardGets++
      const response = await route.fetch()
      if (!badCards) return route.fulfill({ response })
      const body = await response.json()
      return route.fulfill({ response, json: { ...body, data: null } })
    })
    await page.route('**/api/v1/workspace/plans', async route => {
      const response = await route.fetch(), body = await response.json()
      expect(response.status()).toBe(200)
      if (route.request().method() === 'POST') {
        creates++
        return route.fulfill({ response, json: { ...body, data: null } })
      }
      planGets++
      return route.fulfill(badPlans ? { response, json: { ...body, data: [{ ...body.data[0], goal: {} }] } } : { response })
    })
    await page.route(`**/api/v1/workspace/reviews/${card.id}`, async route => {
      ratings++
      const response = await route.fetch(), body = await response.json()
      expect(response.status()).toBe(200)
      expect(body.data.review_count).toBe(1)
      return route.fulfill({ response, json: { ...body, data: null } })
    })
    await page.goto('/review')
    await expect(cards.getByRole('alert')).toContainText('复习卡加载失败')
    await expect(plans.getByRole('alert')).toContainText('学习计划加载失败')
    await expect(page.getByText('今天的复习已就绪', { exact: true })).toHaveCount(0)
    badCards = false
    const oldPlans = planGets
    await cards.getByRole('button', { name: '重试 / Retry' }).click()
    await page.getByRole('button', { name: '查看答案', exact: true }).click()
    expect(planGets).toBe(oldPlans)
    badPlans = false
    const oldCards = cardGets
    await plans.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(plans.getByText('已保存的复习计划', { exact: true })).toBeVisible()
    expect(cardGets).toBe(oldCards)
    await expect(cards.getByText('真实复习答案', { exact: true })).toBeVisible()
    badCards = true
    await cards.getByRole('button', { name: '刷新复习卡', exact: true }).click()
    await expect(cards.getByText('已有复习卡可能不是最新状态。', { exact: true })).toBeVisible()
    await expect(cards.getByRole('button', { name: '基本掌握', exact: true })).toBeDisabled()
    badCards = false
    await cards.getByRole('button', { name: '重试 / Retry' }).click()
    await cards.getByRole('button', { name: '基本掌握', exact: true }).click()
    await expect(page.getByText('评分结果尚未确认，请先核对最新复习状态。', { exact: true })).toBeVisible()
    await expect(cards.getByRole('button', { name: '基本掌握', exact: true })).toBeDisabled()
    expect(sql(`SELECT review_count FROM review_card WHERE id=${card.id} AND user_id=${account.userId}`)).toBe('1')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: testInfo.outputPath('review-unconfirmed.png'), fullPage: false })
    badCards = true
    await page.getByRole('button', { name: '核对最新复习状态', exact: true }).click()
    await expect(page.getByText('核对读取失败，请重试核对；尚未重新提交。', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '已核实，继续操作', exact: true })).toHaveCount(0)
    badCards = false
    await page.getByRole('button', { name: '核对最新复习状态', exact: true }).click()
    await page.getByRole('button', { name: '已核实，继续操作', exact: true }).click()
    await expect(cards.getByText('今天的复习已就绪', { exact: true })).toBeVisible()
    expect(ratings).toBe(1)
    expect(sql(`SELECT COUNT(*) FROM learning_outcome_event WHERE user_id=${account.userId} AND event_type='review'`)).toBe('1')
    await page.getByRole('button', { name: '制定计划', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '制定学习计划', exact: true })
    await dialog.getByLabel('计划名称', { exact: true }).fill('需要核对的计划')
    await dialog.getByLabel('学习目标', { exact: true }).fill('提交后丢失回执仍保留草稿')
    await dialog.getByRole('button', { name: '创建计划', exact: true }).click()
    await expect(dialog.getByText('计划创建结果尚未确认，请先核对已保存计划。', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('计划名称', { exact: true })).toHaveValue('需要核对的计划')
    await expect(dialog.getByRole('button', { name: '创建计划', exact: true })).toBeDisabled()
    badPlans = true
    await dialog.getByRole('button', { name: '核对已保存计划', exact: true }).click()
    await expect(dialog.getByText('核对读取失败，请重试核对；尚未重新提交。', { exact: true })).toBeVisible()
    badPlans = false
    await dialog.getByRole('button', { name: '核对已保存计划', exact: true }).click()
    await expect(dialog.getByText('需要核对的计划', { exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('review-plan-check.png'), fullPage: false })
    await dialog.getByRole('button', { name: '已核实，继续操作', exact: true }).click()
    await dialog.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    expect(creates).toBe(1)
    expect(sql(`SELECT COUNT(*) FROM learning_plan WHERE user_id=${account.userId}`)).toBe('2')
    await expect(plans.getByText('需要核对的计划', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: testInfo.outputPath('review-restored.png'), fullPage: false })
  } finally {
    test.setTimeout(testInfo.timeout + 90000)
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') account = await api(page.request, 'post', '/auth/login', { username, password })
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        await api(cleanup, 'delete', '/profile/account')
        await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
        expect(sql(`SELECT COUNT(*) FROM review_card WHERE user_id=${account.userId}`)).toBe('0')
        expect(sql(`SELECT COUNT(*) FROM learning_plan WHERE user_id=${account.userId}`)).toBe('0')
      } finally { await cleanup.dispose() }
    }
  }
})
