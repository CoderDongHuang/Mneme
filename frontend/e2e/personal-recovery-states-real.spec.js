import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID, createHash } from 'node:crypto'
import { Buffer } from 'node:buffer'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 与存储')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('个人归档真实恢复、结果未知防重放、选择竞态和离页取消', async ({ page }, testInfo) => {
  test.setTimeout(240000); page.setDefaultTimeout(15000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 30000 }).trim()
  const suffix = randomUUID().replaceAll('-', ''), username = `personalstate_${suffix.slice(0, 12)}`
  let account
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after']); expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const wizard = () => page.getByRole('region', { name: '个人恢复向导', exact: true })
  const validate = () => wizard().getByRole('button', { name: '验证清单与文件完整性', exact: true }).click()
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await wizard().scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  let imports = 0
  const importPath = '**/api/v1/workspace/import/archive'
  await page.route(importPath, route => { imports++; return route.continue() })
  try {
    account = await api('post', '/auth/register', { username, password: `PersonalRecovery!${suffix}` })
    expect(String(account.userId)).toMatch(/^\d+$/)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    const name = `personal-archive-${suffix.slice(0, 8)}`
    const kb = await api('post', '/knowledge/base', { name })
    const content = Buffer.from('Personal recovery verification: original document content.\n', 'utf8')
    const upload = await page.request.post('/api/v1/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'recovery-check.txt', mimeType: 'text/plain', buffer: content },
    } })
    expect(upload.ok()).toBe(true)
    const document = (await upload.json()).data
    await expect.poll(async () => (await api('get', `/knowledge/document/${document.id}/status`)).status,
      { timeout: 90000, intervals: [1000, 2000] }).toBe('ready')
    await api('post', '/workspace/plans', { title: 'Personal recovery QA', goal: 'Verify restored card', cards: [{ prompt: 'Recovery check', answer: 'Preserve current data' }] })
    const archive = await page.request.get('/api/v1/workspace/export/archive'); expect(archive.ok()).toBe(true)
    const buffer = await archive.body(), sha256 = createHash('sha256').update(buffer).digest('hex')
    const choose = () => wizard().getByLabel('个人归档 ZIP（最多 50 MiB）').setInputFiles({ name: 'workspace.zip', mimeType: 'application/zip', buffer })
    const countLibraries = async expected => expect((await api('get', '/knowledge/base/list')).filter(item => item.name === name)).toHaveLength(expected)
    await page.goto('/recovery'); await choose(); await validate()
    await expect(wizard().getByText('清单及现有文件哈希校验通过', { exact: true })).toBeVisible()
    await expect(wizard().getByText(sha256, { exact: true })).toBeVisible()
    await expect(wizard().getByText('同名资料库：')).toContainText(name)
    await shot('personal-real-preview.png')
    // Only the explicitly injected read-only revalidation fails.
    const previewPath = '**/api/v1/workspace/import/archive/preview'
    await page.route(previewPath, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '校验暂不可用' }) }), { times: 1 })
    await validate()
    await expect(wizard().getByText('校验暂不可用', { exact: true })).toBeVisible()
    await expect(wizard().getByText('清单及现有文件哈希校验通过', { exact: true })).toHaveCount(0)
    expect(imports).toBe(0)
    await shot('personal-revalidation-failed.png')
    await validate()
    await wizard().getByRole('button', { name: '继续确认', exact: true }).click()
    await wizard().getByLabel('输入 RESTORE MY DATA 确认新增副本').fill('RESTORE MY DATA')
    await wizard().getByRole('button', { name: '执行个人恢复', exact: true }).click()
    await expect(wizard().getByRole('heading', { name: '恢复结果', exact: true })).toBeVisible()
    expect(imports).toBe(1); await countLibraries(2)
    expect((await api('get', '/workspace/reviews')).filter(item => item.prompt === 'Recovery check')).toHaveLength(2)
    const copies = (await api('get', '/knowledge/base/list')).filter(item => item.name === name && item.id !== kb.id)
    const documents = await api('get', `/knowledge/base/${copies[0].id}/documents`)
    expect(documents).toHaveLength(1)
    const original = await page.request.get(`/api/v1/workspace/documents/${documents[0].id}/file`)
    expect(original.ok()).toBe(true); expect(await original.body()).toEqual(content)
    await expect.poll(async () => (await api('get', `/knowledge/document/${documents[0].id}/status`)).status,
      { timeout: 90000, intervals: [1000, 2000] }).toBe('ready')
    await shot('personal-real-restored.png')

    // Execute the real additive import, but deliberately lose its browser receipt.
    await wizard().getByRole('button', { name: '恢复其他归档', exact: true }).click(); await choose(); await validate()
    await wizard().getByRole('button', { name: '继续确认', exact: true }).click()
    await wizard().getByLabel('输入 RESTORE MY DATA 确认新增副本').fill('RESTORE MY DATA')
    await page.route(importPath, async route => {
      imports++
      const response = await route.fetch(); expect(response.ok()).toBe(true)
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '恢复响应连接中断' }) })
    }, { times: 1 })
    await wizard().getByRole('button', { name: '执行个人恢复', exact: true }).click()
    await expect(wizard().getByText(/个人恢复结果未确认/)).toBeVisible()
    await expect(wizard().getByText('清单及现有文件哈希校验通过', { exact: true })).toHaveCount(0)
    await expect(wizard().getByRole('button', { name: '执行个人恢复', exact: true })).toBeDisabled()
    await countLibraries(3); expect(imports).toBe(2)
    await shot('personal-unconfirmed-outcome.png')
    await wizard().getByRole('button', { name: '已核实结果，重新选择归档', exact: true }).click()
    await expect(wizard().getByLabel('个人归档 ZIP（最多 50 MiB）')).toHaveValue('')

    // A delayed actual preview cannot replace a later scope selection.
    let release, started = false
    await page.route(previewPath, async route => {
      const response = await route.fetch(); started = true
      await new Promise(resolve => { release = resolve })
      return route.fulfill({ response }).catch(() => {})
    }, { times: 1 })
    await choose(); await validate(); await expect.poll(() => started).toBe(true)
    await wizard().getByLabel('恢复范围', { exact: true }).selectOption('conversations')
    await validate()
    await expect(wizard().getByText('清单及现有文件哈希校验通过', { exact: true })).toBeVisible()
    release()
    await expect(wizard().getByLabel('恢复范围', { exact: true })).toHaveValue('conversations')
    await expect(wizard().getByRole('row').filter({ hasText: '资料库' }).getByRole('cell').last()).toHaveText('0')

    let releaseDownload, downloading = false, downloads = 0
    page.on('download', () => { downloads++ })
    await page.route('**/api/v1/workspace/export/archive', async route => {
      const response = await route.fetch(); downloading = true
      await new Promise(resolve => { releaseDownload = resolve })
      return route.fulfill({ response }).catch(() => {})
    }, { times: 1 })
    await page.getByRole('button', { name: '下载个人归档', exact: true }).click()
    await expect.poll(() => downloading).toBe(true)
    // SPA navigation exercises unmount cancellation without destroying the tab.
    await page.locator('#global-navigation nav a[href="/chat"]').click()
    await expect(page).toHaveURL(/\/chat$/)
    // URL changes before a lazy route commits; wait for the actual unmount.
    await expect(wizard()).toHaveCount(0)
    await expect(page.locator('#main-content h1')).toBeVisible()
    releaseDownload()
    await page.goto('/recovery')
    await page.getByRole('button', { name: '个人备份', exact: true }).click()
    await expect(page.getByText('本次访问尚未创建个人备份', { exact: true })).toBeVisible()
    expect(downloads).toBe(0); expect(imports).toBe(2)
  } finally {
    if (account) {
      await api('delete', '/profile/account')
      await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 30000, intervals: [1000] }).toBe('0')
    }
  }
})
