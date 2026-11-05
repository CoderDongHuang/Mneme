import { expect, test } from '@playwright/test'
import { execFileSync, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要允许停写的真实测试部署')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('SQLite 停写维护保留活动索引和删除围栏，恢复后知识库仍可使用', async ({ page, playwright }) => {
  test.setTimeout(240000)
  const docker = (...args) => execFileSync('docker', args, { encoding: 'utf8', timeout: 60000 }).trim()
  const ids = docker('ps', '--filter', 'label=com.docker.compose.service=python-agent', '-q').split(/\s+/)
  expect(ids).toHaveLength(1)
  const agent = JSON.parse(docker('inspect', ids[0]))[0]
  const project = agent.Config.Labels['com.docker.compose.project']
  const writers = docker('ps', '--filter', `label=com.docker.compose.project=${project}`, '--format', '{{.ID}} {{.Label "com.docker.compose.service"}}')
    .split('\n').filter(line => / (java-gateway|python-agent)$/.test(line)).map(line => line.split(' ')[0])
  const script = fileURLToPath(new URL('../../scripts/maintain_sqlite.py', import.meta.url))
  const python = process.env.MNEME_MAINTENANCE_PYTHON || 'python'
  const configuration = spawnSync(python, ['-c', "import json,runpy,sys; print(json.dumps(runpy.run_path(sys.argv[1])['config'](json.load(sys.stdin))[1]))", script],
    { input: JSON.stringify(agent), encoding: 'utf8', timeout: 15000 })
  expect(configuration.status).toBe(0)
  const paths = JSON.parse(configuration.stdout).stores
  const mysql = docker('ps', '--filter', `label=com.docker.compose.project=${project}`, '--filter', 'label=com.docker.compose.service=mysql', '-q')
  function query(sql) {
    return execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot mneme -N'],
      { input: sql, encoding: 'utf8', timeout: 15000 }).trim()
  }
  function deletionStatus(entry) {
    expect(String(entry.account.userId)).toMatch(/^\d+$/)
    return query(`SELECT status FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`)
  }
  async function deleted(entry) {
    await expect.poll(() => deletionStatus(entry), { timeout: 90000 }).toBe('completed')
    const report = JSON.parse(query(`SELECT cleanup_report FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`))
    expect(report.status).toBe('verified')
    expect(Object.keys(report.counts)).toHaveLength(19)
    expect(report.counts.sql_session_histories).toBe(0)
    expect(Object.values(report.counts).every(value => value === 0)).toBe(true)
    expect(query(`SELECT COUNT(*) FROM user WHERE id=${entry.account.userId};`)).toBe('0')
  }
  function maintain(apply = false) {
    const result = spawnSync(python, [script, '--container', ids[0], ...(apply ? ['--apply'] : [])],
      { encoding: 'utf8', timeout: 90000 })
    expect(result.error).toBeUndefined()
    return result
  }
  function snapshot() {
    // Short-lived, offline connection using the deployed image and exact mounts.
    return JSON.parse(execFileSync('docker', ['run', '--rm', '-i', '--network', 'none', '--read-only', '--tmpfs', '/tmp', '--volumes-from', ids[0],
      '--entrypoint', 'python', agent.Image, '-c', `
import json,sqlite3,sys
from contextlib import closing
from app.storage.sqlite_maintenance import fingerprint
from pathlib import Path
paths=json.load(sys.stdin)
result={}
for name,path in paths.items():
 with closing(sqlite3.connect(Path(path).as_uri()+'?mode=rw',uri=True)) as db:
  count,digest=fingerprint(db,name)
  result[name]={'rows':count,'digest':digest.hex()}
print(json.dumps(result))
`], { input: JSON.stringify(paths), encoding: 'utf8', timeout: 60000 }))
  }
  async function ready() {
    await expect.poll(() => {
      try {
        return execFileSync('docker', ['exec', ids[0], 'python', '-c', "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health/ready',timeout=5).status)"],
          { encoding: 'utf8', timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'] }).trim()
      } catch { return 'unavailable' }
    }, { timeout: 60000, intervals: [1000, 2000] }).toBe('200')
    await expect.poll(async () => {
      try { return (await accounts[0].client.get('/api/v1/profile')).ok() } catch { return false }
    }, { timeout: 60000 }).toBe(true)
  }
  async function api(client, method, path, options = {}) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await client[method]('/api/v1' + path, options)
      if (response.status() === 429 && attempt < 2) {
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
    throw new Error('rate limit did not recover')
  }
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  const accounts = []
  let stopped = false
  try {
    for (const client of [page.request, other]) {
      const suffix = randomUUID().replaceAll('-', '')
      const account = await api(client, 'post', '/auth/register', { data: { username: `walqa_${suffix.slice(0, 12)}`, password: `WalQA!${suffix}` } })
      const entry = { client, account }
      accounts.push(entry)
      const kb = await api(client, 'post', '/knowledge/base', { data: { name: 'SQLite maintenance QA' } })
      entry.document = await api(client, 'post', '/knowledge/document/upload', { multipart: {
        kbId: String(kb.id), file: { name: 'wal-survivor.txt', mimeType: 'text/plain', buffer: Buffer.from('Walmaintenanceprobe surviving learning material.') },
      } })
      await expect.poll(async () => (await api(client, 'get', `/knowledge/document/${entry.document.id}/status`)).status,
        { timeout: 90000 }).toBe('ready')
    }
    await api(other, 'delete', '/profile/account')
    accounts[1].queued = true
    await deleted(accounts[1])
    const plan = maintain()
    expect(plan.status).toBe(0)
    expect(JSON.parse(plan.stdout).status).toBe('planned')
    expect(maintain(true).status).toBe(1)
    stopped = true
    docker('stop', ...writers)
    const before = snapshot()
    const result = maintain(true)
    expect(result.status, result.stderr).toBe(0)
    const receipt = JSON.parse(result.stdout)
    expect(receipt.status).toBe('completed')
    expect(Object.keys(receipt.stores).sort()).toEqual(Object.keys(before).sort())
    for (const store of Object.values(receipt.stores)) {
      expect(store.logical_data_unchanged).toBe(true)
      expect(store.after_bytes['-wal']).toBe(0)
    }
    expect(snapshot()).toEqual(before)
    docker('start', ...writers)
    stopped = false
    await ready()
    await expect.poll(async () => (await api(page.request, 'get', `/knowledge/document/${accounts[0].document.id}/status`)).status,
      { timeout: 60000 }).toBe('ready')
    // Verify the surviving tenant's indexed content and deleted user's fence.
    const state = JSON.parse(execFileSync('docker', ['exec', '-i', ids[0], 'python', '-c', `
import json,sys
from contextlib import closing
from app.knowledge.generations import generation_store
from app.knowledge.lexical_index import lexical_index
args=json.load(sys.stdin)
with closing(lexical_index._connect()) as db:
 rows=db.execute("SELECT COUNT(*) FROM lexical_chunks WHERE user_id=? AND lexical_chunks MATCH 'Walmaintenanceprobe'",(args['survivor'],)).fetchone()[0]
with generation_store.locked(args['deleted']) as state:
 deleted=state.get('deleted') is True
print(json.dumps({'surviving_chunks':rows,'deleted_fence':deleted}))
`], { input: JSON.stringify({ survivor: String(accounts[0].account.userId), deleted: String(accounts[1].account.userId) }), encoding: 'utf8', timeout: 15000 }))
    expect(state.surviving_chunks).toBeGreaterThan(0)
    expect(state.deleted_fence).toBe(true)
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), accounts[0].account)
    await page.goto('/knowledge')
    await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
    await expect(page.getByText('wal-survivor.txt', { exact: true }).first()).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  } finally {
    if (stopped) docker('start', ...writers)
    if (accounts.length && !accounts[0].queued) await ready()
    for (const entry of accounts) {
      if (!entry.queued) { await api(entry.client, 'delete', '/profile/account'); entry.queued = true }
      await deleted(entry)
    }
    await other.dispose()
  }
})
