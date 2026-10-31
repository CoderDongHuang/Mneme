import { expect, test } from '@playwright/test'
import process from 'node:process'
import { Buffer } from 'node:buffer'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要实际运行的完整服务')
test('初始标签请求晚到时保留编辑并真实保存', async ({ page }) => {
  test.setTimeout(90_000)
  async function data(response) {
    expect(response.ok(), await response.text()).toBeTruthy()
    return (await response.json()).data
  }
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const auth = await data(await page.request.post('/api/v1/auth/register', {
    data: { username: `tagrace_${suffix}`, password: `Mneme_${suffix}!` },
  }))
  let release
  const gate = new Promise(resolve => { release = resolve })
  try {
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
    const kb = await data(await page.request.post('/api/v1/knowledge/base', { data: { name: `标签回归-${suffix}` } }))
    const doc = await data(await page.request.post('/api/v1/knowledge/document/upload', {
      multipart: { kbId: String(kb.id), file: { name: 'tags.txt', mimeType: 'text/plain', buffer: Buffer.from('Tag loading regression document.') } },
    }))
    await expect.poll(async () => (await data(await page.request.get(`/api/v1/knowledge/document/${doc.id}/status`))).status,
      { timeout: 60_000, intervals: [500, 1000] }).toBe('ready')
    const tagsPath = `/api/v1/workspace/documents/${doc.id}/tags`
    // Delay the actual server response; all data and writes use the real stack.
    await page.route(`**${tagsPath}`, async route => {
      if (route.request().method() !== 'GET') return route.continue()
      const response = await route.fetch()
      await gate
      await route.fulfill({ response })
    })
    await page.goto(`/workspace?document=${doc.id}`)
    const input = page.getByLabel('资料标签', { exact: true })
    await input.fill('课程,重点')
    const loaded = page.waitForResponse(response => response.url().endsWith(tagsPath) && response.request().method() === 'GET')
    release()
    await loaded
    await expect(input).toHaveValue('课程,重点')
    await page.getByRole('button', { name: '保存标签', exact: true }).click()
    await expect(page.getByRole('status').filter({ hasText: '标签已保存' })).toBeVisible()
    expect(await data(await page.request.get(tagsPath))).toEqual(['课程', '重点'])
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
    await data(await page.request.delete('/api/v1/profile/account'))
  }
})
