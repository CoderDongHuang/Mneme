import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const ok = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data }) })
const analytics = {
  topics: [{ topic: '链式法则', observations: 8, average_score: 72, success_rate: 0.75, early_score: 65, recent_score: 80 }],
  daily: [{ day: '2026-10-03', event_type: 'review', observations: 4, average_score: 80 }],
  feedback_summary: [{ outcome: 'helpful', citation_rating: 'correct', reason: 'none', observations: 1 }],
  feedback: [{ id: 7, message_id: 44, outcome: 'helpful', citation_rating: 'correct', reason: 'none', note: '资料依据充分' }],
  answers: [{ id: 44, excerpt: '链式法则的应用' }],
  trace_quality: { status: 'available', window_days: 30, sampled_trace_rows: 20, low_intent_confidence: 1, classified: 10, empty_retrievals: 0, retrievals: 10, errors: 0 },
}
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('mneme_auth', JSON.stringify({ userId: 1, username: 'tester', nickname: '测试用户' }))
    window.EventSource = class { addEventListener() {} close() {} }
  })
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname
    const fixtures = {
      '/api/v1/profile': { userId: 1, username: 'tester', nickname: '测试用户' },
      '/api/v1/workspace/tasks': [], '/api/v1/workspace/operations': [], '/api/v1/sessions': [],
      '/api/v1/knowledge/base/list': [{ id: 1, name: '资料库' }],
      '/api/v1/privacy': { providers: ['DeepSeek'], sending_scope: ['检索片段'], cloud_allowed: true, trace_days: 30, trace_max_days: 30 },
      '/api/v1/analytics': analytics,
      '/api/v1/admin/recovery': { runs: [{ id: 1, run_number: 1, created_at: '2026-10-03', conclusion: 'success' }] },
      '/api/v1/admin/operations': {
        checked_at: '2026-10-03T10:00:00Z', health: { mysql: 'up', redis: 'up', agent: { status: 'up' } },
        monitoring: { status: 'not_configured', alerts: [] }, capacity: { status: 'available', disk_usable_bytes: 2 ** 30, disk_total_bytes: 4 * 2 ** 30 },
        storage: { object_storage_ready: true }, rate_limits: { limits: { chat: 20 } }, task_data_status: 'available',
        task_alerts: [], queue: [], sagas: [], deletion_tasks: [],
      },
    }
    return route.fulfill(ok(fixtures[path] ?? []))
  })
})

for (const [path, title] of [['tasks', '任务中心'], ['recovery', '备份恢复管理'], ['privacy', '数据与隐私'], ['operations', '管理员运维中心'], ['analytics', '学习分析']]) {
  test(`${title} WCAG AA、资源与响应式验收`, async ({ page }, testInfo) => {
    await page.goto(`/${path}`)
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
    if (['recovery', 'operations'].includes(path)) {
      await page.getByLabel('管理员凭证').fill('test-admin-token-'.repeat(3))
      await page.getByRole('button', { name: '验证权限' }).click()
      await expect(page.getByRole('button', { name: '锁定', exact: true })).toBeVisible()
      await expect(page.getByText(path === 'operations' ? '检查时间：2026-10-03T10:00:00Z' : '#1 · 2026-10-03')).toBeVisible()
      expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('test-admin-token')
    }
    if (path === 'privacy') await expect(page.getByRole('button', { name: '保存策略' })).toBeVisible()
    if (path === 'analytics') await expect(page.getByRole('table', { name: '主题表现' })).toBeVisible()
    if (path === 'analytics' && page.viewportSize().width < 760) {
      const tableRegion = page.getByRole('region', { name: '主题表现', exact: true })
      await tableRegion.focus()
      await page.keyboard.press('ArrowRight')
      await expect.poll(() => tableRegion.evaluate(node => node.scrollLeft)).toBeGreaterThan(0)
      await tableRegion.evaluate(node => { node.scrollLeft = 0; node.blur() })
    }
    if (path === 'tasks') await expect(page.getByText('暂无符合条件的任务')).toBeVisible()
    const report = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    expect(report.violations).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
    const image = page.getByRole('img', { name: '忆知', exact: true, includeHidden: true })
    expect(await image.evaluate(node => node.complete && node.naturalWidth > 0)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`${path}.png`), fullPage: true, animations: 'disabled' })
  })
}

test('键盘跳转、导航焦点隔离与路由焦点', async ({ page }) => {
  await page.goto('/tasks')
  await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
  await page.getByRole('link', { name: '跳转到主要内容' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
  if (page.viewportSize().width < 760) {
    const toggle = page.getByRole('button', { name: '打开导航', exact: true })
    await toggle.click()
    await expect(page.getByRole('link', { name: '忆知首页' })).toBeFocused()
    const navReport = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
    expect(navReport.violations).toEqual([])
    await expect(page.getByRole('main', { includeHidden: true })).toHaveAttribute('inert', '')
    await page.keyboard.press('Shift+Tab')
    await expect(page.getByRole('button', { name: '关闭导航', exact: true })).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(page.getByRole('button', { name: '退出登录' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: '关闭导航', exact: true })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(toggle).toBeFocused()
    await expect(page.locator('#global-navigation')).toHaveAttribute('inert', '')
    await toggle.click()
  }
  await page.getByRole('link', { name: '学习分析', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: '学习分析', exact: true })).toBeVisible()
  await expect(page.getByRole('main')).toBeFocused()
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert')
})

test('初始请求不加载未访问的页面', async ({ page }) => {
  const scripts = []
  page.on('request', request => { if (request.resourceType() === 'script') scripts.push(request.url()) })
  await page.goto('/tasks')
  await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
  expect(scripts.some(url => /TasksPage-/.test(url))).toBe(true)
  expect(scripts.some(url => /ChatPage-|WorkspacePage-|AnalyticsPage-/.test(url))).toBe(false)
  if (page.viewportSize().width < 760) await page.getByRole('button', { name: '打开导航' }).click()
  await page.getByRole('link', { name: '学习分析', exact: true }).click()
  await expect(page.getByRole('heading', { name: '学习分析' })).toBeVisible()
  expect(scripts.some(url => /AnalyticsPage-/.test(url))).toBe(true)
})

test('聊天 IME 不误发送，引用抽屉可键盘关闭并恢复焦点', async ({ page }) => {
  await page.route('**/api/v1/sessions', route => route.fulfill(ok(route.request().method() === 'POST' ? { id: 1 } : [])))
  await page.route('**/api/v1/chat/stream', route => route.fulfill({ status: 200, contentType: 'text/event-stream', body:
    'event: meta\ndata: {"sources":[{"document_id":"1","document_name":"资料","chunk_content":"原文证据"}]}\n\nevent: token\ndata: {"content":"回答"}\n\n' }))
  await page.goto('/chat')
  const composer = page.getByRole('textbox', { name: '向忆知提问...' })
  await composer.fill('中文输入')
  await composer.evaluate(node => node.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter', isComposing: true })))
  await expect(composer).toHaveValue('中文输入')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const trigger = page.getByRole('button', { name: '查看 1 条资料依据' })
  await trigger.click()
  await expect(page.getByRole('dialog', { name: '资料依据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭资料依据' })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('button', { name: '打开原文定位' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('历史删除按钮可键盘操作且收起后不可聚焦', async ({ page }) => {
  let sessions = [{ id: 5, title: '键盘会话' }]
  await page.route('**/api/v1/sessions', route => route.fulfill(ok(sessions)))
  await page.route('**/api/v1/sessions/5', route => {
    expect(route.request().method()).toBe('DELETE')
    sessions = []
    return route.fulfill(ok({}))
  })
  await page.goto('/chat')
  const toggle = page.getByRole('button', { name: '切换会话栏' })
  if (page.viewportSize().width < 760) await toggle.click()
  const remove = page.getByRole('button', { name: '删除对话：键盘会话' })
  await remove.focus()
  await page.keyboard.press('Enter')
  await expect(remove).toHaveCount(0)
  await toggle.click()
  await expect(page.locator('.chat-history')).toHaveAttribute('inert', '')
})

test('刷新后可用键盘打开持久化历史会话', async ({ page }) => {
  await page.route('**/api/v1/sessions', route => route.fulfill(ok([{ id: 5, title: '历史回答' }])))
  await page.route('**/api/v1/sessions/5/messages', route => route.fulfill(ok([
    { id: 51, role: 'user', content: '确认识别码' },
    { id: 52, role: 'assistant', content: '识别码 QZ-7294' },
  ])))
  await page.goto('/chat')
  await expect(page.getByRole('textbox', { name: '向忆知提问...' })).toBeVisible()
  await page.reload()
  if (page.viewportSize().width < 760) await page.getByRole('button', { name: '切换会话栏' }).click()
  const session = page.getByRole('button', { name: '打开对话：历史回答', exact: true })
  await session.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.message-assistant')).toContainText('QZ-7294')
})
