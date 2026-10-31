import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('真实偏好切换后归档大小、复习次数与后台终态统一显示', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  page.setDefaultTimeout(20_000)
  let account
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
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
    account = await api('post', '/auth/register', { username: `fmtqa_${suffix.slice(0, 12)}`, password: `FmtQA!${suffix}` })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await api('post', '/workspace/plans', { title: 'Formatter QA', goal: 'Verify displayed counts', cards: [{ prompt: 'Formatter review card', answer: Array.from({ length: 100 }, () => randomUUID()).join(' ') }] })
    const kb = await api('post', '/knowledge/base', { name: 'Formatter task QA' })
    await api('delete', `/knowledge/base/${kb.id}`)
    await expect.poll(async () => (await api('get', '/workspace/tasks')).find(task => task.task_type === 'knowledge_base_delete')?.status,
      { timeout: 90_000, intervals: [2000] }).toBe('completed')
    const archive = await page.request.get('/api/v1/workspace/export/archive')
    expect(archive.ok()).toBe(true)
    const buffer = await archive.body()
    // Independent expected value: this fixture is deliberately a small ZIP.
    expect(buffer.length).toBeGreaterThan(1024)
    expect(buffer.length).toBeLessThan(1024 ** 2)
    const size = `${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(buffer.length / 1024)} KiB`
    for (const language of ['zh-CN', 'en']) {
      await api('put', '/settings/preferences', { language, timezone: 'UTC', theme: 'light', notifications: true })
      expect((await api('get', '/settings/preferences')).language).toBe(language)
      await page.goto('/recovery')
      await expect(page.locator('html')).toHaveAttribute('lang', language)
      await page.locator('input[type=file]').setInputFiles({ name: 'formatter-workspace.zip', mimeType: 'application/zip', buffer })
      await page.getByRole('button', { name: language === 'en' ? 'Verify manifest and file integrity' : '验证清单与文件完整性', exact: true }).click()
      await expect(page.locator('.restore-preview')).toBeVisible()
      await expect(page.locator('.restore-preview')).toContainText(size)
      await expect(page.locator('.restore-preview tbody tr').filter({ hasText: language === 'en' ? 'Review cards' : '复习卡' }).locator('td').last()).toHaveText('1')
      await page.screenshot({ path: testInfo.outputPath(`archive-${language}.png`), fullPage: true })
      await page.goto('/review')
      await expect(page.getByRole('heading', { name: 'Formatter review card' })).toBeVisible()
      await expect(page.locator('.study-card .action-row')).toContainText(language === 'en' ? 'Reviewed 0' : '已复习 0')
      await page.goto('/tasks')
      const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: language === 'en' ? /Library deletion/ : /资料库删除/ }) })
      await expect(row.locator('.status-pill')).toHaveText(language === 'en' ? 'Completed' : '已完成')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    }
    await testInfo.attach('formatter-verification.json', { body: JSON.stringify({ archive_bytes: buffer.length, displayed_size: size, languages: ['zh-CN', 'en'], completed_task: true, viewport: testInfo.project.use.viewport }), contentType: 'application/json' })
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
