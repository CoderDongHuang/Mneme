import { expect, request, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

for (const path of ['/chat', '/workspace']) test(`${path} 读取故障独立恢复，草稿、范围和完整回答保留`, async ({ page }, testInfo) => {
  test.setTimeout(240000)
  page.setDefaultTimeout(20000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  const username = `chatread_${suffix.slice(0, 12)}`, password = `ChatRead!${suffix}`
  let account, cleanup, failSessions = true, failBases = true, sessionGets = 0, baseGets = 0, streams = 0, deletes = 0
  async function api(context, method, endpoint, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await context[method]('/api/v1' + endpoint, { data, timeout: 45000 })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${endpoint}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const mobile = testInfo.project.use.viewport.width < 820
  const history = page.getByRole('region', { name: '会话列表读取', exact: true })
  const bases = page.getByRole('region', { name: '对话资料库读取', exact: true })
  const draft = page.getByRole('textbox', { name: '向忆知提问...' })
  const toggle = page.getByRole('button', { name: '切换会话栏', exact: true })
  async function openHistory() {
    if (mobile) await toggle.click()
    // Wait for the actual drawer transition, not an arbitrary screenshot delay.
    await expect(page.locator('.chat-history')).toHaveCSS('opacity', '1')
    if (mobile) {
      const drawer = page.getByRole('dialog', { name: '对话记录', exact: true })
      await expect(drawer).toHaveCSS('background-color', 'rgb(250, 249, 246)')
      await expect(drawer.getByRole('button', { name: '关闭会话栏', exact: true })).toBeInViewport()
    }
  }
  async function closeHistory() { if (mobile) await page.getByRole('dialog', { name: '对话记录', exact: true }).getByRole('button', { name: '关闭会话栏', exact: true }).click() }
  try {
    account = await api(page.request, 'post', '/auth/register', { username, password })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
    await api(cleanup, 'post', '/knowledge/base', { name: 'Chat scope alpha', description: '' })
    await api(cleanup, 'post', '/knowledge/base', { name: 'Chat scope beta', description: '' })
    const active = await api(cleanup, 'post', '/sessions', { title: 'Chat read active' })
    const spare = await api(cleanup, 'post', '/sessions', { title: 'Chat read delete' })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/notifications/stream', route => route.fulfill({ contentType: 'text/event-stream', body: ': isolated\n\n' }))
    await page.route('**/api/v1/sessions', route => {
      if (route.request().method() !== 'GET') return route.continue()
      sessionGets++
      return failSessions ? route.abort('failed') : route.continue()
    })
    await page.route('**/api/v1/knowledge/base/list', route => {
      baseGets++
      return failBases ? route.abort('failed') : route.continue()
    })
    await page.route('**/api/v1/chat/stream', route => {
      streams++; failSessions = true
      return route.continue()
    })
    await page.route(`**/api/v1/sessions/${spare.id}`, route => {
      if (route.request().method() === 'DELETE') deletes++
      return route.continue()
    })
    await page.goto(`${path}?session=${active.id}`)
    await expect(bases.getByRole('alert')).toContainText('资料库加载失败')
    await draft.fill('Draft survives independent reads')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
    await openHistory()
    await expect(history.getByRole('alert')).toContainText('会话列表加载失败')
    await expect(page.getByText('还没有历史对话', { exact: true })).toHaveCount(0)
    const baseBefore = baseGets
    failSessions = false
    await history.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(page.locator('.chat-heading')).toContainText(active.title)
    expect(baseGets).toBe(baseBefore)
    // Successful URL-session selection closes the narrow history automatically.
    if (!mobile) await expect(history.getByRole('alert')).toHaveCount(0)
    await expect(draft).toHaveValue('Draft survives independent reads')
    failBases = false
    const sessionsBefore = sessionGets
    await bases.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(bases.getByRole('alert')).toHaveCount(0)
    expect(sessionGets).toBe(sessionsBefore)
    await page.locator('.kb-selector > button').click()
    for (const label of ['Chat scope alpha', 'Chat scope beta']) {
      const checkbox = page.getByLabel(label, { exact: true })
      await expect(checkbox).toBeChecked()
      await page.locator('.kb-menu label').filter({ has: checkbox }).click()
      await expect(checkbox).not.toBeChecked()
    }
    await expect(page.locator('.kb-selector > button')).toContainText('不使用资料')
    failBases = true
    await page.getByRole('button', { name: '刷新资料库', exact: true }).click()
    await page.getByRole('button', { name: '关闭检索范围', exact: true }).click()
    await expect(bases.getByRole('alert')).toContainText('资料库加载失败')
    await expect(draft).toHaveValue('Draft survives independent reads')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
    failBases = false
    await bases.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(page.locator('.kb-selector > button')).toContainText('不使用资料')
    await page.locator('.kb-selector > button').click()
    for (const label of ['Chat scope alpha', 'Chat scope beta']) await expect(page.getByLabel(label, { exact: true })).not.toBeChecked()
    await page.locator('.kb-selector > button').click()
    await openHistory()
    const search = page.getByRole('textbox', { name: '搜索会话', exact: true })
    await search.fill('no-such-session')
    await expect(page.getByText('没有符合筛选条件的对话', { exact: true })).toBeVisible()
    await expect(page.getByText('还没有历史对话', { exact: true })).toHaveCount(0)
    await search.fill('')
    await closeHistory()
    await draft.fill('hello')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.locator('.message-assistant')).not.toBeEmpty({ timeout: 90000 })
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible({ timeout: 90000 })
    const answer = await page.locator('.message-assistant .message-body').innerText()
    expect(answer.trim().length).toBeGreaterThan(0)
    await expect(page.locator('.message-assistant [role="alert"]')).toHaveCount(0)
    await draft.fill('Next draft remains intact')
    await openHistory()
    await expect(history.getByRole('alert')).toContainText('会话列表加载失败')
    const feedback = history.getByRole('alert')
    expect((await feedback.locator('span').boundingBox()).width).toBeGreaterThan(115)
    const conversation = await page.locator('.conversation').boundingBox()
    const toolbar = await page.locator('.chat-toolbar').boundingBox()
    expect(conversation.y - toolbar.y - toolbar.height).toBeLessThan(2)
    expect(conversation.height).toBeGreaterThan(350)
    await page.screenshot({ path: testInfo.outputPath(`chat-read-${path.slice(1)}.png`), fullPage: false })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    failSessions = false
    const baseAfterAnswer = baseGets
    await history.getByRole('button', { name: '重试 / Retry' }).click()
    await expect(history.getByRole('alert')).toHaveCount(0)
    expect(baseGets).toBe(baseAfterAnswer)
    expect(streams).toBe(1)
    await page.getByRole('button', { name: `删除对话：${spare.title}`, exact: true }).click()
    await expect(page.getByRole('status').filter({ hasText: /会话删除已受理|会话清理已完成/ })).toBeVisible()
    await expect(page.getByRole('button', { name: `打开对话：${spare.title}`, exact: true })).toHaveCount(0)
    expect(deletes).toBe(1)
    await expect.poll(() => sql(`SELECT COUNT(*) FROM chat_session WHERE id=${spare.id}`), { timeout: 60000, intervals: [1000] }).toBe('0')
    await closeHistory()
    await expect(draft).toHaveValue('Next draft remains intact')
    await expect(page.locator('.message-assistant .message-body')).toHaveText(answer, { useInnerText: true })
    await page.screenshot({ path: testInfo.outputPath(`chat-restored-${path.slice(1)}.png`), fullPage: false })
    const saved = await api(cleanup, 'get', `/sessions/${active.id}/messages`)
    const persisted = saved.find(item => item.role === 'assistant')
    expect(persisted).toMatchObject({ status: 'completed' })
    expect(persisted.content.trim().length).toBeGreaterThan(0)
  } finally {
    test.setTimeout(testInfo.timeout + 90000)
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') account = await api(page.request, 'post', '/auth/login', { username, password })
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        await api(cleanup, 'delete', '/profile/account')
        await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
      } finally { await cleanup.dispose() }
    }
  }
})
