import { expect, test } from '@playwright/test'
import process from 'node:process'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { Buffer } from 'node:buffer'

// Explicit opt-in: fault injection touches only this test's newly registered tenant.
test.skip(process.env.MNEME_REAL_E2E !== 'true' || process.env.MNEME_INDEX_QA_FAULTS !== 'true', '需要真实服务和隔离账号故障注入授权')
test('词法索引故障可见、持久任务重试且无原文件也能修复', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  const containers = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=python-agent', '--filter', 'publish=8001', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
  expect(containers).toHaveLength(1)
  const agent = containers[0]
  function python(code, ...args) {
    return execFileSync('docker', ['exec', '-i', agent, 'python', '-', ...args.map(String)], { input: code, encoding: 'utf8', timeout: 30000 }).trim()
  }
  async function api(method, path, options = {}) {
    for (let attempt = 0; attempt < 15; attempt++) {
      const response = await page.request[method]('/api/v1' + path, options)
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
  const suffix = randomUUID().replaceAll('-', '')
  const auth = await api('post', '/auth/register', { data: { username: `indexqa_${suffix.slice(0, 12)}`, password: `IndexQA!${suffix}` } })
  const user = String(auth.userId)
  expect(user).toMatch(/^\d+$/)
  const trigger = `qa_index_${user}`
  const evidence = { base_url: process.env.MNEME_E2E_BASE_URL, viewport: testInfo.project.use.viewport }
  let sourcePath
  let sourceHeld = false
  function holdSource(location, restore = false) {
    // CI uses S3 whereas local installations can use files. Hide both the
    // original object and its shared cache; otherwise this would not prove
    // repair works without reading the source. Credentials stay on stdin.
    const gateways = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=java-gateway', '--filter', 'publish=8080', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim().split(/\s+/)
    expect(gateways).toHaveLength(1)
    const environment = JSON.parse(execFileSync('docker', ['inspect', gateways[0]], { encoding: 'utf8' }))[0].Config.Env
    const config = Object.fromEntries(environment.filter(value => value.startsWith('OBJECT_STORAGE_')).map(value => {
      const split = value.indexOf('='); return [value.slice(0, split), value.slice(split + 1)]
    }))
    python(`import json,sys,hashlib,hmac,datetime,urllib.request,urllib.parse
from pathlib import Path
config=json.loads(${JSON.stringify(JSON.stringify(config))})
location,user,restore=sys.argv[1],sys.argv[2],sys.argv[3]=='true'
root=Path('/data/files')
def request(method,key,body=b''):
 endpoint=config['OBJECT_STORAGE_ENDPOINT'].rstrip('/')
 url=endpoint+'/'+urllib.parse.quote(key,safe='/')
 parsed=urllib.parse.urlsplit(url)
 now=datetime.datetime.now(datetime.timezone.utc)
 stamp=now.strftime('%Y%m%dT%H%M%SZ'); day=stamp[:8]
 digest=hashlib.sha256(body).hexdigest()
 headers={'host':parsed.netloc,'x-amz-content-sha256':digest,'x-amz-date':stamp}
 names=';'.join(sorted(headers))
 canonical='\\n'.join([method,parsed.path,'',''.join(k+':'+headers[k]+'\\n' for k in sorted(headers)),names,digest])
 scope=day+'/us-east-1/s3/aws4_request'
 message='AWS4-HMAC-SHA256\\n'+stamp+'\\n'+scope+'\\n'+hashlib.sha256(canonical.encode()).hexdigest()
 signing=('AWS4'+config['OBJECT_STORAGE_SECRET_KEY']).encode()
 for part in [day,'us-east-1','s3','aws4_request']: signing=hmac.new(signing,part.encode(),hashlib.sha256).digest()
 signature=hmac.new(signing,message.encode(),hashlib.sha256).hexdigest()
 headers['Authorization']='AWS4-HMAC-SHA256 Credential='+config['OBJECT_STORAGE_ACCESS_KEY']+'/'+scope+', SignedHeaders='+names+', Signature='+signature
 with urllib.request.urlopen(urllib.request.Request(url,data=body if method=='PUT' else None,headers=headers,method=method),timeout=15) as response: return response.read()
if location.startswith('s3://'):
 uri=urllib.parse.urlsplit(location)
 assert uri.netloc==config.get('OBJECT_STORAGE_BUCKET','mneme')
 assert uri.path.startswith('/users/'+user+'/knowledge/') and '..' not in uri.path
 key=uri.netloc+uri.path
 p=root/'.object-cache'/(hashlib.sha256(location.encode()).hexdigest()[:24]+'-'+Path(uri.path).name)
 backup=root/('.index-qa-'+user+'.object-hold')
 if restore:
  if backup.exists():
   request('PUT',key,backup.read_bytes()); backup.unlink()
 else:
  assert not backup.exists()
  backup.write_bytes(request('GET',key)); request('DELETE',key)
else:
 p=Path(location).resolve()
 assert p.is_relative_to(root/user) and (restore or p.is_file())
hold=Path(str(p)+'.index-qa-hold')
if restore:
 if hold.exists(): hold.rename(p)
elif p.exists(): p.rename(hold)
if not restore: assert not p.exists()
`, location, user, restore)
  }
  function removeFault() {
    python(`import sqlite3,sys\nfrom app.core.config import settings\nwith sqlite3.connect(settings.lexical_index_path) as c: c.execute('DROP TRIGGER IF EXISTS '+sys.argv[1])`, trigger)
  }
  try {
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), auth)
    python(`import sqlite3,sys\nfrom app.core.config import settings\nuser=sys.argv[1]\nassert user.isdigit()\nwith sqlite3.connect(settings.lexical_index_path) as c:\n c.execute("CREATE TRIGGER qa_index_"+user+" BEFORE INSERT ON lexical_chunks_content WHEN NEW.c1='"+user+"' BEGIN SELECT RAISE(ABORT,'isolated QA index fault'); END")`, user)
    const kb = await api('post', '/knowledge/base', { data: { name: 'Index reconciliation QA' } })
    const doc = await api('post', '/knowledge/document/upload', { multipart: {
      kbId: String(kb.id), file: { name: 'index-repair.txt', mimeType: 'text/plain', buffer: Buffer.from('Reconciliation evidence: lexical restoration preserves the existing vector index.') },
    } })
    const status = () => api('get', `/knowledge/document/${doc.id}/status`)
    await expect.poll(async () => (await status()).status, { timeout: 60000, intervals: [500, 1000, 2000] }).toBe('index_pending')
    const before = await status()
    const originalReport = JSON.parse(before.parseReport)
    expect(originalReport.vector_index_version).toMatch(/^[a-f0-9]{64}$/)
    expect(originalReport.lexical_index_version).toBeNull()
    const snapshot = () => JSON.parse(python(`import json,sys,hashlib\nfrom app.knowledge.vector_store import vector_store\nc=vector_store.get_collection(sys.argv[1],sys.argv[2],validate_profile=False)\nr=c.get(where={'document_id':sys.argv[3]},include=['documents','metadatas','embeddings'])\nprint(json.dumps({'sha256':hashlib.sha256(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest(),'count':len(r['ids'])}))`, user, kb.id, `doc_${doc.id}`).split('\n').at(-1))
    const vectorBefore = snapshot()
    expect(vectorBefore.count).toBeGreaterThan(0)
    // Verify that normal Gateway retrieval still authorizes dense-only documents.
    const search = await api('get', `/workspace/retrieval/debug?kbId=${kb.id}&query=reconciliation&documentIds=${doc.id}`)
    expect(search.chunks.length).toBeGreaterThan(0)
    await page.goto('/knowledge')
    await page.getByRole('button', { name: 'index-repair.txt', exact: true }).click()
    const health = page.getByRole('region', { name: '索引一致性' })
    await expect(health).toContainText('向量索引可用，词法索引待修复')
    await expect(page.locator('.document-paper pre')).toContainText('Reconciliation evidence')
    await page.screenshot({ path: testInfo.outputPath('index-pending.png'), fullPage: true })
    await health.getByRole('button', { name: '修复词法索引', exact: true }).click()
    let task
    await expect.poll(async () => {
      task = (await api('get', '/workspace/tasks')).find(item => item.task_type === 'document_index_repair')
      return task?.status
    }, { timeout: 90000, intervals: [1000, 2000, 3000] }).toBe('failed')
    expect(task.attempt_count).toBe(3)
    expect((await status()).status).toBe('index_pending')
    evidence.failed_repair_is_durable_and_retryable = true
    removeFault()
    // Move only this QA document, restore it in finally before account cleanup.
    sourcePath = before.filePath
    sourceHeld = true
    holdSource(sourcePath)
    await page.goto('/tasks')
    await page.getByRole('row').filter({ hasText: '词法索引修复' }).getByRole('button', { name: /index-repair\.txt/ }).click()
    await page.getByRole('button', { name: '重试任务', exact: true }).click()
    await expect.poll(async () => (await status()).status, { timeout: 60000, intervals: [500, 1000, 2000] }).toBe('ready')
    const after = await status()
    const report = JSON.parse(after.parseReport)
    expect(report.vector_index_version).toBe(originalReport.vector_index_version)
    expect(report.lexical_index_version).toBe(report.vector_index_version)
    expect(report.index_status).toBe('ready')
    expect(report.content_sha256).toBe(originalReport.content_sha256)
    expect(report.pages).toEqual(originalReport.pages)
    expect(snapshot()).toEqual(vectorBefore)
    const lexical = JSON.parse(python(`import json,sys\nfrom app.knowledge.lexical_index import lexical_index\nprint(json.dumps({'version':lexical_index.document_version(*sys.argv[1:4]),'matches':len(lexical_index.search(sys.argv[1],sys.argv[2],'reconciliation',5))}))`, user, kb.id, `doc_${doc.id}`).split('\n').at(-1))
    expect(lexical.version).toBe(report.vector_index_version)
    expect(lexical.matches).toBeGreaterThan(0)
    // Repair is complete while the source is absent. Restore it before preview QA.
    holdSource(sourcePath, true)
    sourceHeld = false
    await page.goto('/knowledge')
    await page.getByRole('button', { name: 'index-repair.txt', exact: true }).click()
    await expect(health).toContainText('向量与词法索引版本一致')
    await expect(health.getByRole('button', { name: '修复词法索引' })).toHaveCount(0)
    await expect(page.locator('.document-paper pre')).toContainText('Reconciliation evidence')
    await page.screenshot({ path: testInfo.outputPath('index-repaired.png'), fullPage: true })
    evidence.ready_versions_match = true
    evidence.repair_without_source = true
    evidence.vector_snapshot_unchanged = true
    evidence.lexical_search_restored = true
    await testInfo.attach('index-reconciliation.json', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' })
  } finally {
    removeFault()
    if (sourceHeld) holdSource(sourcePath, true)
    await api('delete', '/profile/account')
    await expect.poll(() => python(`import sys,sqlite3\nfrom app.core.config import settings\nfrom app.knowledge.vector_store import vector_store\nwith sqlite3.connect(settings.lexical_index_path) as c: n=c.execute('SELECT COUNT(*) FROM lexical_chunks WHERE user_id=?',(sys.argv[1],)).fetchone()[0]\nprint(str(n)+':'+str(len(vector_store.list_user_collections(sys.argv[1]))))`, user).split('\n').at(-1),
      { timeout: 60000, intervals: [1000, 2000] }).toBe('0:0')
  }
})
