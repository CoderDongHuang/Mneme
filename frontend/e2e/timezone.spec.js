import { expect, test } from '@playwright/test'

const instant = '2026-10-30T18:30:00Z'
const ok = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data }) })

test('保存与刷新后的语言时区覆盖会话、文档版本、解析、任务、计划和审计', async ({ page }) => {
  let preferences = { language: 'zh-CN', timezone: 'Asia/Shanghai', theme: 'light', notifications: false }
  await page.addInitScript(() => {
    localStorage.setItem('mneme_auth', JSON.stringify({ userId: 1, username: 'timezone-test' }))
    window.EventSource = class { addEventListener() {} close() {} }
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (path === '/settings/preferences') {
      if (route.request().method() === 'PUT') preferences = route.request().postDataJSON()
      return route.fulfill(ok(preferences))
    }
    const fixtures = {
      '/profile': { userId: 1, username: 'timezone-test', role: 'admin' },
      '/profile/sessions': [{ session_id: 'tz-session', last_seen_at: instant }],
      '/sessions': [{ id: 5, title: 'Timezone conversation', updatedAt: '2026-10-30T18:30:00' }],
      '/workspace/tasks': [{ task_id: 'tz-task', task_type: 'document_ingest', file_name: 'timezone.txt', status: 'completed', created_at: instant }],
      '/workspace/operations': [{ operation_id: 'tz-task', step: 'indexed', status: 'completed', created_at: '2026-10-30 18:30:00' }],
      '/workspace/plans': [{ id: 1, title: 'Calendar date stays October 30', goal: 'A date is not an instant', target_date: '2026-10-30' }],
      '/workspace/reviews': [],
      '/knowledge/base/list': [{ id: 1, name: 'Timezone library' }],
      '/knowledge/base/1/documents': [{ id: 1, fileName: 'timezone.txt', status: 'ready', updatedAt: instant, parseReport: JSON.stringify({ indexed_at: instant, parser_version: 'tz-v1' }) }],
      '/knowledge/document/1/versions': [{ version_number: 1, active: true, sha256: 'abc123', created_at: instant }],
      '/admin/operations': { checked_at: instant, health: {}, monitoring: { alerts: [] }, task_alerts: [], queue: [], sagas: [], deletion_tasks: [] },
    }
    await route.fulfill(ok(fixtures[path] ?? []))
  })

  for (const value of [
    { language: 'en', timezone: 'Europe/Amsterdam', time: /Oct 30, 2026, 07:30\sPM/, date: 'Oct 30, 2026', day: '2026-10-30', calendar: 'Oct 30, 2026' },
    { language: 'zh-CN', timezone: 'Asia/Shanghai', time: '2026年10月31日 02:30', date: '2026年10月31日', day: '2026-10-31', calendar: '2026年10月30日' },
  ]) {
    await page.goto('/profile')
    await expect(page.locator('.profile-page')).toBeVisible()
    const selects = page.locator('.account-aside form select')
    await selects.nth(0).selectOption(value.language)
    await selects.nth(1).selectOption(value.timezone)
    await page.locator('.account-aside form button').click()
    await expect.poll(() => preferences.timezone).toBe(value.timezone)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('lang', value.language)
    await expect(selects.nth(1)).toHaveValue(value.timezone)
    await page.locator('.segmented-tabs button').nth(1).click()
    await expect(page.locator('.profile-security .plain-list')).toContainText(value.time)

    await page.goto('/tasks')
    await expect(page.locator('.reference-table tbody')).toContainText(value.time)
    await expect(page.locator('.activity-timeline')).toContainText(value.time)

    await page.goto('/review')
    await expect(page.locator('.plain-list')).toContainText(value.calendar)

    await page.goto('/knowledge')
    await expect(page.locator('.document-row time')).toHaveText(value.date)
    await page.locator('.row-actions > summary').click()
    await page.locator('.row-actions details > summary').click()
    await expect(page.locator('.parse-report')).toContainText(value.time)
    await page.locator('.row-actions button').first().click()
    await expect(page.locator('.version-list')).toContainText(value.time)

    await page.goto('/chat')
    if (page.viewportSize().width < 760) await page.getByRole('button', { name: /切换会话栏|Toggle conversation history/ }).click()
    await expect(page.locator('.session-open small')).toHaveText(value.date)
    await page.locator('.history-filters details summary').click()
    const filter = page.locator('.history-filters input[type=date]')
    await filter.fill(value.day)
    await expect(page.locator('.session-open')).toHaveCount(1)
    await filter.fill(value.day === '2026-10-31' ? '2026-10-30' : '2026-10-31')
    await expect(page.locator('.session-open')).toHaveCount(0)

    await page.goto('/operations')
    await page.getByLabel(/管理员凭证|Administrator credential/).fill('timezone-admin-test-'.repeat(3))
    await page.getByRole('button', { name: /验证权限|Verify permission/ }).click()
    await expect(page.locator('#main-content')).toContainText(value.time)
  }
})
