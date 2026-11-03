import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs/promises'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('分析真实窗口与导出一致，反馈成功后读取断网保留回执和草稿', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30_000 }).trim()
  const suffix = randomUUID().replaceAll('-', '')
  let account, failReads = true, abortCount = 0
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 4) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const result = await response.json(); expect(result.code).toBe(200)
      return result.data
    }
    throw new Error('Rate limit did not recover')
  }
  const fits = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  try {
    account = await api('post', '/auth/register', { username: `analyticsqa_${suffix.slice(0, 10)}`, password: `AnalyticsQA!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    const session = await api('post', '/sessions', { title: 'Analytics state QA' })
    expect(String(session.id)).toMatch(/^\d+$/)
    // Seed only this disposable user's observations and completed answer. All HTTP reads/writes stay real.
    const answerId = sql(`INSERT INTO chat_message(session_id,role,content,status) VALUES (${session.id},'assistant','Analytics QA answer','completed'); SELECT LAST_INSERT_ID();`)
    expect(answerId).toMatch(/^\d+$/)
    sql(`INSERT INTO learning_outcome_event(user_id,event_type,topic,score,success,created_at) VALUES (${account.userId},'quiz','QA recent topic',80,1,UTC_TIMESTAMP()),(${account.userId},'review','QA older topic',60,0,DATE_SUB(UTC_TIMESTAMP(),INTERVAL 15 DAY));`)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    // Explicit transport fault injection; no synthetic successful API response.
    await page.route('**/api/v1/analytics?*', route => {
      if (failReads) { abortCount++; return route.abort('internetdisconnected') }
      return route.continue()
    })
    await page.goto('/analytics')
    await expect(page.getByRole('heading', { name: '学习分析', exact: true })).toBeVisible()
    const retry = page.getByRole('button', { name: '重试 / Retry', exact: true })
    await expect(retry).toBeVisible()
    await expect(page.locator('.reference-metrics')).toHaveCount(0)
    const exportButton = page.getByRole('button', { name: '导出含统计口径的报告', exact: true })
    await expect(exportButton).toBeDisabled()
    failReads = false
    await retry.click()
    await expect(page.locator('.topic-performance')).toHaveCount(2)
    await page.getByLabel('时间窗口', { exact: true }).selectOption('7')
    await expect(page.locator('.topic-performance')).toHaveCount(1)
    await expect(page.locator('.topic-performance')).toContainText('QA recent topic')
    await expect(exportButton).toBeEnabled()
    const downloadEvent = page.waitForEvent('download')
    await exportButton.click()
    const download = await downloadEvent
    expect(download.suggestedFilename()).toBe('mneme-learning-7days.json')
    const report = JSON.parse(await fs.readFile(await download.path(), 'utf8'))
    expect(report.window_days).toBe(7)
    expect(report.data.window_days).toBe(7)
    expect(report.data.topics.map(row => row.topic)).toEqual(['QA recent topic'])
    await page.locator('.analysis-diagnostics > summary').click()
    await page.getByLabel('回答', { exact: true }).selectOption(answerId)
    await page.getByLabel('备注', { exact: true }).fill('QA feedback draft retained')
    failReads = true
    await page.getByRole('button', { name: '保存反馈', exact: true }).click()
    await expect(page.getByText('反馈已保存', { exact: true })).toBeVisible()
    await expect(retry).toBeVisible()
    await expect(page.getByText('已有分析可能不是最新状态，刷新成功后可导出报告或修改反馈。', { exact: true })).toBeVisible()
    await expect(page.getByLabel('备注', { exact: true })).toHaveValue('QA feedback draft retained')
    await expect(exportButton).toBeDisabled()
    await expect(page.getByRole('button', { name: '保存反馈', exact: true })).toBeDisabled()
    expect(sql(`SELECT COUNT(*) FROM rag_quality_feedback WHERE user_id=${account.userId} AND message_id=${answerId} AND note='QA feedback draft retained';`)).toBe('1')
    await fits()
    await page.screenshot({ path: testInfo.outputPath('analytics-stale-feedback.png'), fullPage: true })
    failReads = false
    await retry.click()
    const deleteButton = page.getByRole('button', { name: /^删除反馈 \d+$/ })
    await expect(deleteButton).toHaveCount(1)
    await expect(deleteButton).toBeEnabled()
    await deleteButton.click()
    await expect(page.getByText('反馈已删除', { exact: true })).toBeVisible()
    await expect(deleteButton).toHaveCount(0)
    expect(sql(`SELECT COUNT(*) FROM rag_quality_feedback WHERE user_id=${account.userId};`)).toBe('0')
    await expect(exportButton).toBeEnabled()
    await fits()
    expect(abortCount).toBeGreaterThanOrEqual(2)
  } finally {
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId};`), { timeout: 60_000, intervals: [1000] }).toBe('0')
      for (const table of ['learning_outcome_event', 'rag_quality_feedback']) expect(sql(`SELECT COUNT(*) FROM ${table} WHERE user_id=${account.userId};`)).toBe('0')
    }
  }
})
