import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实全栈服务及隔离测试账号')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('账号文件清单异常阻断删除，恢复后清除当前和历史文件且保留其他租户', async ({ page, playwright }, testInfo) => {
  test.setTimeout(240000)
  function container(service) {
    const ids = execFileSync('docker', ['ps', '--filter', `label=com.docker.compose.service=${service}`, '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
    expect(ids).toHaveLength(1)
    return ids[0]
  }
  const mysql = container('mysql'), agent = container('python-agent')
  const gatewayConfig = JSON.parse(execFileSync('docker', ['inspect', container('java-gateway')], { encoding: 'utf8' }))[0]
  const environment = Object.fromEntries(gatewayConfig.Config.Env.map(value => {
    const at = value.indexOf('='); return [value.slice(0, at), value.slice(at + 1)]
  }))
  function query(sql) {
    return execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot mneme -N'],
      { input: sql, encoding: 'utf8', timeout: 15000 }).trim()
  }
  function storage(entry) {
    expect(String(entry.account.userId)).toMatch(/^\d+$/)
    // Credentials stay in process memory/stdin. Probe real local files, S3
    // prefix and exact cache paths independently of the deletion response.
    const input = { user: String(entry.account.userId), paths: entry.locations || [], environment }
    return JSON.parse(execFileSync('docker', ['exec', '-i', agent, 'python', '-c', `
import datetime,hashlib,hmac,json,sys,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
args=json.load(sys.stdin); env=args['environment']; user=args['user']
root=Path(env.get('FILE_STORAGE_PATH','/data/files')); hashes=[]; remote=0
for path in sorted((root/user).rglob('*')):
 if path.is_file(): hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
if env.get('STORAGE_BACKEND','local')=='s3':
 endpoint=env['OBJECT_STORAGE_ENDPOINT'].rstrip('/'); bucket=env.get('OBJECT_STORAGE_BUCKET','mneme')
 def request(query):
  url=urllib.parse.urlsplit(endpoint); uri=url.path+'/'+bucket
  now=datetime.datetime.now(datetime.timezone.utc); stamp=now.strftime('%Y%m%dT%H%M%SZ'); date=stamp[:8]
  payload=hashlib.sha256(b'').hexdigest(); scope=date+'/us-east-1/s3/aws4_request'
  headers={'host':url.netloc,'x-amz-content-sha256':payload,'x-amz-date':stamp}
  canonical='GET\\n'+uri+'\\n'+query+'\\n'+''.join(k+':'+v+'\\n' for k,v in sorted(headers.items()))+'\\nhost;x-amz-content-sha256;x-amz-date\\n'+payload
  string='AWS4-HMAC-SHA256\\n'+stamp+'\\n'+scope+'\\n'+hashlib.sha256(canonical.encode()).hexdigest()
  key=('AWS4'+env['OBJECT_STORAGE_SECRET_KEY']).encode()
  for value in (date,'us-east-1','s3','aws4_request'): key=hmac.new(key,value.encode(),hashlib.sha256).digest()
  signature=hmac.new(key,string.encode(),hashlib.sha256).hexdigest()
  headers['Authorization']='AWS4-HMAC-SHA256 Credential='+env['OBJECT_STORAGE_ACCESS_KEY']+'/'+scope+', SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature='+signature
  with urllib.request.urlopen(urllib.request.Request(endpoint+'/'+bucket+'?'+query,headers=headers),timeout=10) as response: return ET.fromstring(response.read())
 token=None
 while True:
  params={'list-type':'2','prefix':'users/'+user+'/'}
  if token: params['continuation-token']=token
  result=request(urllib.parse.urlencode(sorted(params.items()),quote_via=urllib.parse.quote))
  remote+=len(result.findall('{*}Contents'))
  if result.findtext('{*}IsTruncated')!='true': break
  token=result.findtext('{*}NextContinuationToken'); assert token
 for location in sorted(set(args['paths'])):
  if location.startswith('s3://'):
   path=root/'.object-cache'/(hashlib.sha256(location.encode()).hexdigest()[:24]+'-'+location.rsplit('/',1)[1])
   if path.exists(): hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
print(json.dumps({'objects':remote,'file_hashes':sorted(hashes)}))
`], { input: JSON.stringify(input), encoding: 'utf8', timeout: 30000 }))
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
    throw new Error('Rate limit did not recover')
  }
  async function ready(entry) {
    await expect.poll(async () => (await api(entry.client, 'get', `/knowledge/document/${entry.document.id}/status`)).status,
      { timeout: 90000, intervals: [500, 1000, 2000] }).toBe('ready')
  }
  function counts(entry) {
    return query(`SELECT COUNT(*) FROM user WHERE id=${entry.account.userId};
SELECT COUNT(*) FROM knowledge_document WHERE kb_id=${entry.kb?.id || 0};
SELECT COUNT(*) FROM knowledge_document_version WHERE document_id=${entry.document?.id || 0};`)
  }
  function report(entry) {
    return JSON.parse(query(`SELECT cleanup_report FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`))
  }
  function privacyFault(entry, enable) {
    expect(String(entry.account.userId)).toMatch(/^\d+$/)
    execFileSync('docker', ['exec', '-i', agent, 'python', '-c', `
import json,sys
from app.core.privacy import privacy_store
from app.core.config import settings
args=json.load(sys.stdin); user=args['user']; assert user.isascii() and user.isdecimal()
assert settings.auxiliary_store_backend=='sqlite', 'This QA fixture requires the isolated SQLite deployment'
with privacy_store._local() as db:
 db.execute('DROP TRIGGER IF EXISTS qa_account_privacy_'+user)
 if args['enable']:
  db.execute('INSERT OR REPLACE INTO user_privacy VALUES(?,0,1)',(user,))
  db.execute("CREATE TRIGGER qa_account_privacy_"+user+" BEFORE DELETE ON user_privacy WHEN OLD.user_id='"+user+"' BEGIN SELECT RAISE(IGNORE); END")
`], { input: JSON.stringify({ user: String(entry.account.userId), enable }), timeout: 15000 })
  }
  async function inspectSaga(entry, verified) {
    const operation = query(`SELECT operation_id FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`)
    await page.goto('/operations')
    await page.getByLabel('管理员凭证').fill(environment.ADMIN_API_TOKEN, { timeout: 15000 })
    await page.getByRole('button', { name: '验证权限', exact: true }).click()
    await page.getByText('账号删除 Saga', { exact: true }).click()
    const row = page.getByRole('row').filter({ has: page.getByRole('cell', { name: operation, exact: true }) })
    const summary = row.getByText(verified ? '清理已核验' : '清理待核验', { exact: true })
    await expect(summary).toBeVisible()
    await summary.click()
    await expect(row.getByText('隐私设置', { exact: true })).toBeVisible()
    await expect(row.getByText('数据库记录', { exact: true })).toBeVisible()
  }
  async function deleted(entry) {
    await expect.poll(() => query(`SELECT status FROM account_deletion_task WHERE user_id=${entry.account.userId} ORDER BY id DESC LIMIT 1;`),
      { timeout: 90000, intervals: [500, 1000, 2000] }).toBe('completed')
    expect(counts(entry)).toBe('0\n0\n0')
    expect(storage(entry)).toEqual({ objects: 0, file_hashes: [] })
    const receipt = report(entry)
    expect(receipt.status).toBe('verified')
    expect(Object.keys(receipt.counts)).toHaveLength(19)
    expect(receipt.counts.sql_session_histories).toBe(0)
    expect(Object.values(receipt.counts).every(value => value === 0)).toBe(true)
    entry.verified = true
  }
  const other = await playwright.request.newContext({ baseURL: process.env.MNEME_E2E_BASE_URL })
  const accounts = []
  let brokenVersion, originalHex, privacyBlocked
  function restore() {
    if (!brokenVersion) return
    expect(originalHex).toMatch(/^[0-9A-F]+$/)
    query(`UPDATE knowledge_document_version SET file_path=UNHEX('${originalHex}') WHERE id=${brokenVersion};`)
    brokenVersion = undefined
  }
  try {
    for (const client of [page.request, other]) {
      const suffix = randomUUID().replaceAll('-', '')
      const account = await api(client, 'post', '/auth/register', { data: { username: `fileqa_${suffix.slice(0, 12)}`, password: `FileQA!${suffix}` } })
      const entry = { client, account }
      accounts.push(entry)
      const kb = await api(client, 'post', '/knowledge/base', { data: { name: 'Account files QA' } })
      entry.kb = kb
      entry.document = await api(client, 'post', '/knowledge/document/upload', { multipart: {
        kbId: String(kb.id), file: { name: 'account-original.txt', mimeType: 'text/plain', buffer: Buffer.from('Original isolated account file cleanup material.') },
      } })
      await ready(entry)
      entry.locations = query(`SELECT file_path FROM knowledge_document_version WHERE document_id=${entry.document.id};`).split('\n')
    }
    const [target, protectedUser] = accounts
    await api(target.client, 'post', `/knowledge/document/${target.document.id}/replace`, { multipart: {
      file: { name: 'account-replacement.txt', mimeType: 'text/plain', buffer: Buffer.from('Replacement isolated account file cleanup material.') },
    } })
    await ready(target)
    target.locations = query(`SELECT file_path FROM knowledge_document_version WHERE document_id=${target.document.id};`).split('\n')
    expect(counts(target)).toBe('1\n1\n2')
    expect(storage(target).file_hashes).toHaveLength(2)
    const protectedFiles = storage(protectedUser)
    expect(protectedFiles.file_hashes).toHaveLength(1)
    const manifest = query(`SELECT id,HEX(file_path) FROM knowledge_document_version WHERE document_id=${target.document.id} ORDER BY version_number LIMIT 1;`).split('\t')
    expect(manifest[0]).toMatch(/^\d+$/)
    ;[brokenVersion, originalHex] = manifest
    // Only this newly created tenant's historical SQL manifest is corrupted;
    // all HTTP, worker, storage and UI responses remain real.
    query(`UPDATE knowledge_document_version SET file_path='' WHERE id=${brokenVersion};`)
    await page.addInitScript(value => {
      if (!localStorage.getItem('mneme_auth')) localStorage.setItem('mneme_auth', JSON.stringify(value))
    }, target.account)
    await page.goto('/privacy')
    await page.getByRole('button', { name: '删除我的账号', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '删除账号及全部关联数据' })
    await dialog.getByRole('textbox', { name: '确认文字 / Confirmation' }).fill('DELETE MY ACCOUNT')
    page.once('dialog', alert => alert.accept())
    await dialog.getByRole('button', { name: '删除我的账号', exact: true }).click()
    target.queued = true
    await expect.poll(() => query(`SELECT status FROM account_deletion_task WHERE user_id=${target.account.userId} ORDER BY id DESC LIMIT 1;`),
      { timeout: 60000, intervals: [250, 500] }).toBe('retry')
    query(`UPDATE account_deletion_task SET next_attempt_at=TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP()) WHERE user_id=${target.account.userId} AND status='retry';`)
    expect(query(`SELECT current_step FROM account_deletion_task WHERE user_id=${target.account.userId};`)).toBe('session_cleanup')
    expect(counts(target)).toBe('1\n1\n2')
    expect(report(target).counts.files).toBe(-1)
    expect(storage(protectedUser)).toEqual(protectedFiles)
    restore()
    privacyBlocked = target
    privacyFault(target, true)
    query(`UPDATE account_deletion_task SET next_attempt_at=UTC_TIMESTAMP() WHERE user_id=${target.account.userId} AND status='retry';`)
    await expect.poll(() => report(target).counts.privacy_rows, { timeout: 60000 }).toBe(1)
    await expect.poll(() => query(`SELECT status FROM account_deletion_task WHERE user_id=${target.account.userId};`), { timeout: 60000 }).toBe('retry')
    query(`UPDATE account_deletion_task SET next_attempt_at=TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP()) WHERE user_id=${target.account.userId} AND status='retry';`)
    expect(report(target).status).toBe('pending')
    expect(counts(target)).toBe('1\n1\n2')
    // Grant only this newly created QA account the real administrator role.
    // AdminRoute and the gateway both verify the stored role independently.
    expect(String(protectedUser.account.userId)).toMatch(/^\d+$/)
    query(`UPDATE user SET role='admin' WHERE id=${protectedUser.account.userId};`)
    expect((await api(protectedUser.client, 'get', '/profile')).role).toBe('admin')
    // Inspect the report through the real authenticated administrator page.
    await page.context().addCookies((await other.storageState()).cookies)
    await page.evaluate(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), protectedUser.account)
    await inspectSaga(target, false)
    privacyFault(target, false)
    privacyBlocked = undefined
    query(`UPDATE account_deletion_task SET next_attempt_at=UTC_TIMESTAMP() WHERE user_id=${target.account.userId} AND status='retry';`)
    await deleted(target)
    await inspectSaga(target, true)
    expect(counts(protectedUser)).toBe('1\n1\n1')
    expect(storage(protectedUser)).toEqual(protectedFiles)
    // Check the surviving tenant through its actual authenticated page.
    await page.context().addCookies((await other.storageState()).cookies)
    await page.evaluate(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), protectedUser.account)
    await page.goto('/knowledge')
    await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
    await expect(page.getByText('account-original.txt', { exact: true }).first()).toBeVisible()
    await ready(protectedUser)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await testInfo.attach('account-files-readback.json', { body: JSON.stringify({ invalid_history_blocks_completion: true, sql_manifest_retained: true,
      restored_manifest_retries: true, privacy_residual_blocks_completion: true, admin_failure_and_success_reports: true,
      all_19_counts_zero: true, mysql_readback_zero: true, current_and_history_files_zero: true, protected_tenant_unchanged: true }), contentType: 'application/json' })
  } finally {
    restore()
    if (privacyBlocked) privacyFault(privacyBlocked, false)
    for (const entry of accounts) {
      if (!entry.queued) { await api(entry.client, 'delete', '/profile/account'); entry.queued = true }
      if (!entry.verified) {
        query(`UPDATE account_deletion_task SET next_attempt_at=UTC_TIMESTAMP() WHERE user_id=${entry.account.userId} AND status='retry';`)
        await deleted(entry)
      }
    }
    await other.dispose()
  }
})
