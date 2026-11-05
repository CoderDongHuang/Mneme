import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要实际运行的完整服务')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('独立解析阶段保留多格式、OCR、页码、表格与实际预览', async ({ page }) => {
  test.setTimeout(300_000)
  let account
  async function api(method, path, options = {}) {
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await page.request[method]('/api/v1' + path, options)
      if (response.status() === 429 && attempt < 4) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250)
        continue
      }
      expect(response.ok(), `${method} ${path}: ${response.status()}`).toBe(true)
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api('post', '/auth/register', { data: { username: `parserqa_${suffix.slice(0, 12)}`, password: `ParserQA!${suffix}` } })
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    const kb = await api('post', '/knowledge/base', { data: { name: 'Parser boundary QA' } })
    let pdf
    for (const extension of ['txt', 'md', 'pdf', 'docx', 'pptx', 'xlsx', 'csv', 'html']) {
      const name = `rag-fixture.${extension}`
      const doc = await api('post', '/knowledge/document/upload', { multipart: {
        kbId: String(kb.id), file: { name, mimeType: 'application/octet-stream', buffer: fs.readFileSync(`../test-fixtures/${name}`) },
      } })
      await expect.poll(async () => (await api('get', `/knowledge/document/${doc.id}/status`)).status,
        { timeout: 90_000, intervals: [1000, 2000] }).toMatch(/^(ready|partial)$/)
      const preview = await api('get', `/workspace/documents/${doc.id}/preview`)
      expect(preview.parse_report.parser_version).toBe('mneme-structured-v3')
      expect(preview.parse_report.chunks.length).toBeGreaterThan(0)
      expect(preview.parse_report.chunks.some(chunk => chunk.content.includes('QZ-7294'))).toBe(true)
      expect(preview.parse_report.pages.every(page => page.page > 0)).toBe(true)
      if (['xlsx', 'csv'].includes(extension)) expect(preview.parse_report.chunks.some(chunk => chunk.type === 'table')).toBe(true)
      if (extension === 'pdf') pdf = doc
    }
    const scan = await api('post', '/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'scanned-acceptance.pdf', mimeType: 'application/pdf', buffer: fs.readFileSync('../test-fixtures/scanned-acceptance.pdf') },
    } })
    await expect.poll(async () => (await api('get', `/knowledge/document/${scan.id}/status`)).status,
      { timeout: 90_000, intervals: [1000, 2000] }).toMatch(/^(ready|partial)$/)
    const scanned = await api('get', `/workspace/documents/${scan.id}/preview`)
    expect(scanned.parse_report.pages[0].text).toContain('SCAN-ALPHA')
    expect(scanned.parse_report.pages[0].ocr_regions.length).toBeGreaterThan(0)
    expect(scanned.parse_report.pages[0].ocr_regions.every(region => region.confidence >= 0 && region.confidence <= 1)).toBe(true)
    const image = await page.request.get(`/api/v1/workspace/documents/${pdf.id}/pages/1`)
    expect(image.ok()).toBe(true)
    expect((await image.body()).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
    await page.goto(`/workspace?document=${scan.id}`)
    const previewImage = page.getByRole('img', { name: '第 1 页 OCR 区域预览' })
    await expect(previewImage).toBeVisible()
    await expect.poll(() => previewImage.evaluate(img => img.naturalWidth)).toBeGreaterThan(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
