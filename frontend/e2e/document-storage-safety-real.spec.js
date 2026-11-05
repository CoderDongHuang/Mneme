import { expect, request, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { Buffer } from 'node:buffer'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、解析服务和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('十次替换后可从真实版本界面恢复原文且清理无残留', async ({ page }, testInfo) => {
  test.setTimeout(300000)
  let account, cleanup
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 15000 }).trim()
  async function api(method, path, options = {}, context = page.request) {
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await context[method]('/api/v1' + path, { ...options, timeout: 45000 })
      if (response.status() === 429 && attempt < 4) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api('post', '/auth/register', { data: { username: `storageqa_${suffix.slice(0, 12)}`, password: `Storage!${suffix}` } })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    const kb = await api('post', '/knowledge/base', { data: { name: 'Storage lifecycle QA' } })
    const upload = index => ({ name: `version-${index}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`Storage lifecycle evidence. Version ${index}. Original marker QZ-7294-${index}.`) })
    const document = await api('post', '/knowledge/document/upload', { multipart: { kbId: String(kb.id), file: upload(0) } })
    const ready = () => expect.poll(async () => (await api('get', `/knowledge/document/${document.id}/status`)).status, { timeout: 60000, intervals: [500, 1000] }).toMatch(/^(ready|partial)$/)
    await ready()
    for (let index = 1; index <= 10; index++) {
      await api('post', `/knowledge/document/${document.id}/replace`, { multipart: { file: upload(index) } })
      await ready()
    }
    const versions = await api('get', `/knowledge/document/${document.id}/versions`)
    expect(versions.map(version => version.version_number)).toEqual([11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
    expect(versions.filter(version => version.active).map(version => version.version_number)).toEqual([11])
    expect(new Set(versions.map(version => version.sha256)).size).toBe(11)
    await page.goto('/knowledge')
    await expect(page.getByLabel('资料库', { exact: true })).toHaveValue(String(kb.id))
    await page.getByLabel('文档操作：version-10.txt', { exact: true }).click()
    await page.getByRole('button', { name: '版本历史', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '版本历史', exact: true })
    await expect(dialog.getByRole('button', { name: /v11 · version-10.txt/ })).toBeDisabled()
    page.once('dialog', confirmation => confirmation.accept())
    await dialog.getByRole('button', { name: /v1 · version-0.txt/ }).click()
    await expect(dialog).toBeHidden()
    await ready()
    const restored = await api('get', `/knowledge/document/${document.id}/versions`)
    expect(restored.filter(version => version.active).map(version => version.version_number)).toEqual([1])
    const preview = await api('get', `/workspace/documents/${document.id}/preview`)
    expect(preview.parse_report.chunks.some(chunk => chunk.content.includes('QZ-7294-0'))).toBe(true)
    expect(preview.parse_report.chunks.some(chunk => chunk.content.includes('QZ-7294-10'))).toBe(false)
    expect(sql(`SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=${document.id};`)).toBe('11')
    await page.reload()
    await page.getByLabel('文档操作：version-0.txt', { exact: true }).click()
    await page.getByRole('button', { name: '版本历史', exact: true }).click()
    await expect(dialog.getByRole('button', { name: /v1 · version-0.txt/ })).toBeDisabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('storage-versions.png'), fullPage: true, animations: 'disabled' })
  } finally {
    test.setTimeout(testInfo.timeout + 300000)
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        await api('delete', '/profile/account', {}, cleanup)
        expect(String(account.userId)).toMatch(/^\d+$/)
        await expect.poll(() => sql(`SELECT (SELECT COUNT(*) FROM user WHERE id=${account.userId})+(SELECT COUNT(*) FROM auth_session WHERE user_id=${account.userId});`), { timeout: 60000, intervals: [1000, 2000] }).toBe('0')
      } finally { await cleanup.dispose() }
    }
  }
})
