import { expect, test } from '@playwright/test'
import process from 'node:process'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_DELETION_QA_FAULTS !== 'true', '需要真实服务和隔离租户删除故障注入')

test('文档与知识库删除必须独立核验，残留可见且恢复后可重试', async ({ page, playwright }, testInfo) => {
  test.setTimeout(240000)
  const containers = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--filter', 'publish=8001', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
  expect(containers).toHaveLength(1)
  const agent = containers[0]
  function python(code, ...args) {
    return execFileSync('docker', ['exec', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30000 }).trim().split('\n').at(-1)
  }
  async function api(client, method, path, options = {}) {
    for (let attempt = 0; attempt < 15; attempt++) {
      const response = await client[method]('/api/v1' + path, options)
      if (response.status() === 429) {
        await page.waitForTimeout(Math.max(1000, Math.min(60000, Number(response.headers()['retry-after'] || 5) * 1000)))
        continue
      }
      expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy()
      const body = await response.json()
      expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  const accounts = []
  let user
  const evidence = { base_url: process.env.MNEME_E2E_BASE_URL, viewport: testInfo.project.use.viewport, scopes: [] }
  function fault(enabled) {
    if (!user) return
    python(`import sqlite3,sys
from app.core.config import settings
user,enabled=sys.argv[1],sys.argv[2]=='true'
assert user.isdigit()
with sqlite3.connect(settings.lexical_index_path) as c:
 c.execute('DROP TRIGGER IF EXISTS qa_delete_'+user)
 if enabled: c.execute("CREATE TRIGGER qa_delete_"+user+" BEFORE DELETE ON lexical_chunks_content WHEN OLD.c1='"+user+"' BEGIN SELECT RAISE(ABORT,'isolated QA deletion fault'); END")
print('ok')`, user, enabled)
  }
  function readback(owner, kb, doc) {
    return JSON.parse(python(`import json,sys
from app.knowledge.vector_store import vector_store
print(json.dumps(vector_store.deletion_report(sys.argv[1],sys.argv[2],sys.argv[3] or None)))`, owner, kb, doc ? `doc_${doc}` : ''))
  }
  async function upload(client, kb, name) {
    const doc = await api(client, 'post', '/knowledge/document/upload', { multipart: {
      kbId: String(kb), file: { name, mimeType: 'text/plain', buffer: Buffer.from('Deletion evidence: isolated tenant material for strict cleanup verification.') },
    } })
    await expect.poll(async () => (await api(client, 'get', `/knowledge/document/${doc.id}/status`)).status,
      { timeout: 60000, intervals: [500, 1000, 2000] }).toBe('ready')
    return doc
  }
  async function taskFor(type, aggregate) {
    return (await api(page.request, 'get', '/workspace/tasks')).find(task => task.task_type === type && String(task.aggregate_id) === String(aggregate))
  }
  function receipt(task) { return typeof task.cleanup_report === 'string' ? JSON.parse(task.cleanup_report) : task.cleanup_report }
  try {
    for (const client of [page.request, other]) {
      const suffix = randomUUID().replaceAll('-', '')
      const account = await api(client, 'post', '/auth/register', { data: { username: `deleteqa_${suffix.slice(0, 12)}`, password: `DeleteQA!${suffix}` } })
      accounts.push({ client, account })
    }
    user = String(accounts[0].account.userId)
    await page.addInitScript(auth => localStorage.setItem('mneme_auth', JSON.stringify(auth)), accounts[0].account)
    const kb = await api(page.request, 'post', '/knowledge/base', { data: { name: 'Deletion readback QA' } })
    const otherKb = await api(other, 'post', '/knowledge/base', { data: { name: 'Protected tenant QA' } })
    const protectedDoc = await upload(other, otherKb.id, 'protected.txt')
    const protectedBefore = readback(String(accounts[1].account.userId), otherKb.id, protectedDoc.id)
    expect(protectedBefore.fts_rows).toBeGreaterThan(0)
    expect(protectedBefore.qdrant_chunks).toBeGreaterThan(0)
    for (const scope of ['document', 'knowledge_base']) {
      const doc = await upload(page.request, kb.id, `${scope}-delete.txt`)
      const type = scope === 'document' ? 'document_delete' : 'knowledge_base_delete'
      const aggregate = scope === 'document' ? doc.id : kb.id
      fault(true)
      await api(page.request, 'delete', scope === 'document' ? `/knowledge/document/${doc.id}` : `/knowledge/base/${kb.id}`)
      let task
      await expect.poll(async () => { task = await taskFor(type, aggregate); return task?.status },
        { timeout: 90000, intervals: [1000, 2000, 3000] }).toBe('failed')
      const failed = receipt(task)
      expect(failed.status).toBe('pending')
      expect(failed.counts.qdrant_chunks).toBe(0)
      expect(failed.counts.fts_rows).toBeGreaterThan(0)
      expect(failed.counts.files).toBeGreaterThan(0)
      expect(failed.counts.mysql_rows).toBeGreaterThan(0)
      expect(readback(String(accounts[1].account.userId), otherKb.id, protectedDoc.id)).toEqual(protectedBefore)
      await page.goto('/tasks')
      const row = page.getByRole('row').filter({ has: page.getByRole('cell', { name: scope === 'document' ? '文档删除' : '资料库删除', exact: true }) })
      await row.getByRole('button').click()
      const checklist = page.getByRole('region', { name: '清理核验', exact: true })
      await expect(checklist).toContainText('清理待核验')
      await checklist.getByText('清理待核验', { exact: true }).click()
      await expect(checklist).toContainText('词法索引行')
      await page.screenshot({ path: testInfo.outputPath(`${scope}-cleanup-pending.png`), fullPage: true })
      fault(false)
      await page.getByRole('button', { name: '重试任务', exact: true }).click()
      await expect.poll(async () => { task = await taskFor(type, aggregate); return task?.status },
        { timeout: 60000, intervals: [500, 1000, 2000] }).toBe('completed')
      const verified = receipt(task)
      expect(verified.status).toBe('verified')
      expect(Object.values(verified.counts).every(count => count === 0)).toBe(true)
      expect(Object.values(readback(user, kb.id, scope === 'document' ? doc.id : null)).every(count => count === 0)).toBe(true)
      await expect(checklist).toContainText('清理已核验', { timeout: 15000 })
      await page.screenshot({ path: testInfo.outputPath(`${scope}-cleanup-verified.png`), fullPage: true })
      expect(readback(String(accounts[1].account.userId), otherKb.id, protectedDoc.id)).toEqual(protectedBefore)
      evidence.scopes.push({ scope, pending: failed.counts, verified: verified.counts, protected_tenant_unchanged: true })
    }
    await testInfo.attach('deletion-readback.json', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' })
  } finally {
    fault(false)
    for (const { client } of accounts) await api(client, 'delete', '/profile/account')
    await other.dispose()
  }
})
