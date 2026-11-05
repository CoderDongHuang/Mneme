import { expect, test } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_RATE_LIMIT_QA !== 'true', '需要隔离的真实维护限流回归')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('维护桶真实429后任务持久退避且不耗尽预算，重启后自动核验完成', async ({ page, playwright }) => {
  test.setTimeout(240_000)
  page.setDefaultTimeout(20_000)
  const container = service => execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  const gateway = container('java-gateway'), mysql = container('mysql'), agent = container('python-agent')
  for (const id of [gateway, mysql, agent]) expect(id).toMatch(/^[a-f0-9]+$/)
  const config = JSON.parse(execFileSync('docker', ['inspect', gateway], { encoding: 'utf8' }))[0]
  const env = Object.fromEntries(config.Config.Env.map(value => { const at = value.indexOf('='); return [value.slice(0, at), value.slice(at + 1)] }))
  const image = JSON.parse(execFileSync('docker', ['inspect', agent], { encoding: 'utf8' }))[0].Image
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B mneme'], { input: query, encoding: 'utf8', timeout: 20_000 }).trim()
  const second = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  let account, deletedAccount, taskId, flood
  let floodDone = Promise.resolve()
  async function api(context, method, path, data) {
    const response = await context[method]('/api/v1' + path, data === undefined ? {} : { data })
    expect(response.status(), `${method} ${path}`).toBe(200)
    const payload = await response.json(); expect(payload.code).toBe(200); return payload.data
  }
  async function register(context) {
    const suffix = randomUUID().replaceAll('-', '')
    return api(context, 'post', '/auth/register', { username: `backqa_${suffix.slice(0, 12)}`, password: `BackoffQA!${suffix}` })
  }
  try {
    account = await register(page.request); deletedAccount = await register(second)
    for (const value of [account.userId, deletedAccount.userId]) expect(String(value)).toMatch(/^\d+$/)
    const kb = await api(page.request, 'post', '/knowledge/base', { name: 'Backoff QA' })
    expect(String(kb.id)).toMatch(/^\d+$/)
    // A read-only probe shares the actual Gateway network namespace/source IP.
    // No route mocking, limiter mutation or production rate-limit weakening.
    const probe = `import concurrent.futures,json,sys,time,urllib.request,urllib.error
args=json.load(sys.stdin)
def read(_):
 req=urllib.request.Request(args['url'],headers={'X-Internal-Service-Token':args['token']})
 try:
  with urllib.request.urlopen(req,timeout=5) as response: return response.status
 except urllib.error.HTTPError as error: return error.code
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
 announced=False
 for response in concurrent.futures.as_completed([pool.submit(read,i) for i in range(100)]):
  if response.result()==429 and not announced:
   print(json.dumps({'limited':True}),flush=True); announced=True
 deadline=time.monotonic()+12
 while time.monotonic()<deadline:
  list(pool.map(read,range(8))); time.sleep(.05)
`
    flood = spawn('docker', ['run', '--rm', '-i', '--network', `container:${gateway}`, '--entrypoint', 'python', image, '-c', probe], { stdio: ['pipe', 'pipe', 'pipe'] })
    let output = '', diagnostics = ''
    flood.stderr.on('data', chunk => { diagnostics += chunk.toString() })
    flood.stdout.on('data', chunk => { output += chunk.toString() })
    floodDone = new Promise((resolve, reject) => {
      flood.on('error', reject)
      flood.on('close', code => code === 0 ? resolve() : reject(new Error(`maintenance probe exit ${code}: ${diagnostics.slice(-500)}`)))
    })
    // Attach a handler immediately; failures are rethrown when awaited below.
    floodDone.catch(() => {})
    flood.stdin.end(JSON.stringify({ url: `${env.MNEME_PYTHON_AGENT_URL || env.PYTHON_AGENT_URL || 'http://python-agent:8001'}/api/v1/knowledge/admin/deletion-report?user_id=${account.userId}&kb_id=${kb.id}`, token: env.INTERNAL_SERVICE_TOKEN }))
    await expect.poll(() => output.includes('"limited": true'), { timeout: 60_000 }).toBe(true)
    await api(page.request, 'delete', `/knowledge/base/${kb.id}`)
    await api(second, 'delete', '/profile/account')
    await expect.poll(() => sql(`SELECT status FROM processing_task WHERE user_id=${account.userId} AND task_type='knowledge_base_delete'`), { timeout: 20_000 }).toBe('retry')
    await expect.poll(() => sql(`SELECT status FROM account_deletion_task WHERE user_id=${deletedAccount.userId}`), { timeout: 20_000 }).toBe('retry')
    taskId = sql(`SELECT task_id FROM processing_task WHERE user_id=${account.userId} AND task_type='knowledge_base_delete'`)
    expect(taskId).toMatch(/^task_[a-f0-9]+$/)
    expect(sql(`SELECT attempt_count,error_code,owner_token IS NULL,TIMESTAMPDIFF(SECOND,UTC_TIMESTAMP(6),next_attempt_at)>=15 FROM processing_task WHERE task_id='${taskId}'`)).toBe('0\tRATE_LIMITED\t1\t1')
    expect(sql(`SELECT attempt_count,owner_token IS NULL FROM account_deletion_task WHERE user_id=${deletedAccount.userId}`)).toBe('0\t1')
    expect(sql(`SELECT COUNT(*) FROM knowledge_base WHERE id=${kb.id}`)).toBe('1')
    expect(sql(`SELECT COUNT(*) FROM user WHERE id=${deletedAccount.userId}`)).toBe('1')
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.goto('/tasks')
    const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: /资料库删除/ }) })
    await expect(row).toContainText('0/5', { timeout: 30_000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await floodDone
    execFileSync('docker', ['restart', gateway], { timeout: 60_000, stdio: 'pipe' })
    await expect.poll(async () => { try { return (await page.request.get('/api/v1/health', { timeout: 3000 })).ok() } catch { return false } }, { timeout: 90_000 }).toBe(true)
    await expect.poll(() => sql(`SELECT status FROM processing_task WHERE task_id='${taskId}'`), { timeout: 90_000, intervals: [2000] }).toBe('completed')
    await expect.poll(() => sql(`SELECT status FROM account_deletion_task WHERE user_id=${deletedAccount.userId}`), { timeout: 90_000, intervals: [2000] }).toBe('completed')
    for (const query of [`SELECT cleanup_report FROM processing_task WHERE task_id='${taskId}'`, `SELECT cleanup_report FROM account_deletion_task WHERE user_id=${deletedAccount.userId}`]) {
      const report = JSON.parse(sql(query)); expect(report.status).toBe('verified')
      expect(Object.values(report.counts).every(count => count === 0)).toBe(true)
    }
    expect(sql(`SELECT COUNT(*) FROM knowledge_base WHERE id=${kb.id}`)).toBe('0')
    expect(sql(`SELECT COUNT(*) FROM user WHERE id=${deletedAccount.userId}`)).toBe('0')
    await page.reload(); await expect(row.locator('.status-pill')).toHaveText('已完成', { timeout: 30_000 })
  } finally {
    try { await floodDone } finally {
      try {
        try {
          if (account) {
            await api(page.request, 'delete', '/profile/account')
            await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 90_000, intervals: [2000] }).toBe('0')
          }
        } finally {
          if (deletedAccount) {
            if (sql(`SELECT status FROM user WHERE id=${deletedAccount.userId}`) === 'active') await api(second, 'delete', '/profile/account')
            await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${deletedAccount.userId}`), { timeout: 90_000, intervals: [2000] }).toBe('0')
          }
        }
      } finally { await second.dispose() }
    }
  }
})
