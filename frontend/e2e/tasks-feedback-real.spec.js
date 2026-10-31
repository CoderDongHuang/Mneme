import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实任务按最新阶段展示，失败不泄露内部错误，诊断只复制允许字段', async ({ page }, testInfo) => {
  test.setTimeout(300_000)
  page.setDefaultTimeout(20_000)
  let account
  async function api(method, path, options = {}) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const response = await page.request[method]('/api/v1' + path, options)
      if (response.status() === 429) {
        await page.waitForTimeout(Math.min(60_000, Math.max(1000, Number(response.headers()['retry-after'] || 5) * 1000)))
        continue
      }
      expect(response.ok(), `${method} ${path}`).toBe(true)
      const result = await response.json()
      expect(result.code).toBe(200)
      return result.data
    }
    throw new Error('Rate limit did not recover')
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api('post', '/auth/register', { data: { username: `taskqa_${suffix.slice(0, 12)}`, password: `TaskQA!${suffix}` } })
    await page.addInitScript(value => {
      localStorage.setItem('mneme_auth', JSON.stringify(value))
      // Exercise the real copy action without depending on OS clipboard grants.
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.taskDiagnosticCopy = text } } })
    }, account)
    const kb = await api('post', '/knowledge/base', { data: { name: 'Task feedback QA' } })
    for (let i = 0; i < 3; i++) {
      const doc = await api('post', '/knowledge/document/upload', { multipart: {
        kbId: String(kb.id), file: { name: `task-evidence-${i}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`Task QA evidence number ${i}. A clear source of retrievable text.`) },
      } })
      await expect.poll(async () => (await api('get', `/knowledge/document/${doc.id}/status`)).status,
        { timeout: 60_000, intervals: [2000] }).toBe('ready')
    }
    const failedDoc = await api('post', '/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'task-blank-private.txt', mimeType: 'text/plain', buffer: Buffer.from('   \n\t   ') },
    } })
    await expect.poll(async () => (await api('get', '/workspace/tasks')).find(task => task.aggregate_id === failedDoc.id)?.status,
      { timeout: 120_000, intervals: [2000] }).toBe('failed')
    const tasks = await api('get', '/workspace/tasks')
    const logs = await api('get', '/workspace/operations')
    expect(logs.length).toBeGreaterThan(8)
    const failed = tasks.find(task => task.aggregate_id === failedDoc.id)
    expect(failed.error_message).toBeTruthy()
    const stages = logs.filter(event => event.operation_id === failed.task_id)
    expect(stages.length).toBeGreaterThan(1)
    await page.goto('/tasks')
    const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: /task-blank-private.txt/ }) })
    await expect(row.locator('td').nth(2)).toHaveText(stages[0].step)
    const activity = page.locator('.activity-timeline li strong')
    await expect(activity).toHaveCount(8)
    for (let i = 0; i < 8; i++) await expect(activity.nth(i)).toContainText(logs[i].step)
    await row.getByRole('button').click()
    const detail = page.getByRole('complementary', { name: '任务详情' }).or(page.getByRole('dialog', { name: '任务详情' }))
    if (await detail.getAttribute('role') === 'dialog') {
      const bounds = await detail.boundingBox()
      expect(bounds.y).toBeGreaterThanOrEqual(0)
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(page.viewportSize().height + 1)
      for (const element of [detail.getByRole('heading', { name: '任务详情' }), detail.getByRole('button', { name: /^关闭/ })]) {
        await expect(element).toBeInViewport({ ratio: 1 })
      }
    }
    await expect(detail).toContainText(String(failedDoc.id))
    await expect(detail).toContainText(`阶段：${stages[0].step}`)
    await expect(detail).toContainText('修复原因后重试')
    await expect(page.locator('body')).not.toContainText(failed.error_message)
    await detail.getByRole('button', { name: '复制诊断信息' }).click()
    const copied = await page.evaluate(() => JSON.parse(window.taskDiagnosticCopy))
    expect(copied.schema).toBe('mneme.task-diagnostics.v1')
    expect(copied.task.aggregate_id).toBe(failedDoc.id)
    expect(copied.stages.map(event => event.step)).toEqual(stages.map(event => event.step))
    expect(JSON.stringify(copied)).not.toMatch(/task-blank-private|error_message|payload|https?:\/\//)
    await detail.getByText('错误详情与阶段记录', { exact: true }).click()
    await expect(detail.locator('details')).toHaveAttribute('open', '')
    const timeline = detail.locator('.task-timeline li strong')
    await expect(timeline.first()).toBeVisible()
    await expect(timeline.first()).toContainText(stages.at(-1).step)
    await expect(timeline.last()).toContainText(stages[0].step)
    await timeline.first().scrollIntoViewIfNeeded()
    await expect(timeline.first()).toBeInViewport({ ratio: 1 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('task-feedback.png') })
    if (await detail.getAttribute('role') === 'dialog') {
      await detail.getByRole('heading', { name: '任务详情' }).scrollIntoViewIfNeeded()
      await page.screenshot({ path: testInfo.outputPath('task-drawer-header.png') })
    }
    await testInfo.attach('task-feedback-verification.json', { body: JSON.stringify({ task_count: tasks.length, event_count: logs.length, diagnostic_schema: copied.schema, latest_stage: stages[0].step, raw_error_hidden: true }), contentType: 'application/json' })
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
