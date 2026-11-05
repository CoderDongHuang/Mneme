import { expect, request, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import process from 'node:process'
import { setTimeout as delay } from 'node:timers/promises'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('测验业务数据校验、真实草稿损坏回执和评分幂等重放', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(20000)
  const mysql = execFileSync('docker', ['ps', '--filter', 'label=com.docker.compose.service=mysql', '--filter', 'label=com.docker.compose.container-number=1', '--format', '{{.ID}}'], { encoding: 'utf8' }).trim()
  expect(mysql).toMatch(/^[a-f0-9]+$/)
  const sql = query => execFileSync('docker', ['exec', '-i', mysql, 'sh', '-c', 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -N mneme'], { input: query, encoding: 'utf8' }).trim()
  const suffix = randomUUID().replaceAll('-', ''), username = `quizread_${suffix.slice(0, 10)}`, password = `Quiz!${suffix}`
  let account, cleanup, badList = true, badBases = true, badDraft = true, badHistory = true, badSave = true, listGets = 0
  const submissions = []
  async function api(context, method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await context[method]('/api/v1' + path, { data, timeout: 45000 })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after']); expect(seconds > 0 && seconds <= 60).toBe(true)
        await delay(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200); return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    account = await api(page.request, 'post', '/auth/register', { username, password })
    cleanup = await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
    await api(cleanup, 'post', '/workspace/import', { version: 1, knowledge_bases: [{ id: 1, name: '测验校验真实资料库' }], quizzes: [1, 2].map(id => ({ id, kb_id: 1, title: `核验测验 ${id}`, topic: '状态回归', questions_json: JSON.stringify([{ type: 'short', prompt: `核验题目 ${id}`, answer: '原子持久化', key_points: ['持久化'], evidence: '持久化后可重新读取。' }]) })) })
    const quizzes = await api(cleanup, 'get', '/workspace/quizzes'), quiz = quizzes.find(item => item.title === '核验测验 1')
    expect(quiz).toBeTruthy()
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/notifications/stream', route => route.fulfill({ contentType: 'text/event-stream', body: ': isolated\n\n' }))
    await page.route('**/api/v1/workspace/quizzes', async route => {
      listGets++
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
      return route.fulfill(badList ? { response, json: { ...body, data: body.data.map(item => ({ ...item, questions_json: '[{"type":"short","prompt":{}}]' })) } } : { response })
    })
    await page.route('**/api/v1/knowledge/base/list', async route => {
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
      return route.fulfill(badBases ? { response, json: { ...body, data: null } } : { response })
    })
    await page.route('**/api/v1/workspace/quizzes/*/draft', async route => {
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
      const bad = route.request().method() === 'GET' ? badDraft : badSave
      return route.fulfill(bad ? { response, json: { ...body, data: { ...body.data, answers_json: '[{}]' } } } : { response })
    })
    await page.route('**/api/v1/workspace/quizzes/*/attempts', async route => {
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
      return route.fulfill(badHistory ? { response, json: { ...body, data: {} } } : { response })
    })
    await page.route('**/api/v1/workspace/quizzes/*/submit', async route => {
      submissions.push(route.request().postDataJSON())
      const response = await route.fetch(), body = await response.json(); expect(response.status()).toBe(200)
      return route.fulfill(submissions.length === 1 ? { response, json: { ...body, data: { ...body.data, feedback: [{}] } } } : { response })
    })
    await page.goto('/quiz')
    const list = page.getByRole('navigation', { name: '我的测验', exact: true })
    await expect(list.getByText('测验列表加载失败，请重试。', { exact: true })).toBeVisible()
    await expect(page.getByText('还没有测验。', { exact: true })).toHaveCount(0)
    await page.locator('.page-header').getByRole('button', { name: '创建测验', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '创建知识测验', exact: true })
    await expect(dialog.getByText('测验资料库加载失败，请重试。', { exact: true })).toBeVisible()
    await dialog.getByRole('textbox', { name: '测验主题', exact: true }).fill('保留校验主题')
    badBases = false
    const before = listGets
    await dialog.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(dialog.getByRole('combobox', { name: '资料库', exact: true })).not.toHaveValue('')
    expect(listGets).toBe(before)
    await expect(dialog.getByRole('textbox', { name: '测验主题', exact: true })).toHaveValue('保留校验主题')
    await dialog.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    badList = false
    await list.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await list.getByRole('button', { name: /^核验测验 1/ }).click()
    await expect(page.getByText('测验草稿加载失败，请重试。', { exact: true })).toBeVisible()
    const history = page.getByRole('region', { name: '作答记录', exact: true })
    await expect(history.getByText('作答记录加载失败，请重试。', { exact: true })).toBeVisible()
    expect(sql(`SELECT COUNT(*) FROM quiz_draft WHERE user_id=${account.userId}`)).toBe('0')
    await shot('quiz-invalid-draft-history.png')
    badDraft = false
    await page.locator('.study-card').getByRole('button', { name: '重试 / Retry', exact: true }).click()
    const answer = page.getByRole('textbox', { name: '你的答案', exact: true })
    await answer.fill('尚需巩固的答案')
    await list.getByRole('button', { name: /^核验测验 2/ }).click()
    await expect(page.getByText('草稿保存失败：草稿保存回执无法确认，请重试保存。当前答案已保留，请重试保存后再切换。', { exact: true })).toBeVisible()
    await expect(answer).toHaveValue('尚需巩固的答案')
    expect(JSON.parse(sql(`SELECT answers_json FROM quiz_draft WHERE user_id=${account.userId} AND quiz_id=${quiz.id}`))).toEqual(['尚需巩固的答案'])
    badSave = false
    await page.locator('.reference-quiz > .feedback-block').getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(page.getByText('第 1 / 1 题 · 草稿已保存', { exact: true })).toBeVisible()
    await list.getByRole('button', { name: /^核验测验 2/ }).click()
    await expect(page.getByRole('heading', { name: '核验题目 2', exact: true })).toBeVisible()
    await list.getByRole('button', { name: /^核验测验 1/ }).click()
    await expect(answer).toHaveValue('尚需巩固的答案')
    await page.getByRole('button', { name: '提交测验（已答 1 题）', exact: true }).click()
    await expect(page.getByText('测验提交回执无法确认，请重试确认提交。', { exact: true })).toBeVisible()
    await expect(answer).toBeDisabled()
    await expect(list.getByRole('button', { name: /^核验测验 2/ })).toBeDisabled()
    await shot('quiz-unconfirmed-submission.png')
    await page.getByRole('button', { name: '提交测验（已答 1 题）', exact: true }).click()
    await expect(page.getByText(/本次原始得分 0/)).toBeVisible()
    expect(submissions).toHaveLength(2); expect(submissions[0]).toEqual(submissions[1])
    expect(sql(`SELECT COUNT(*) FROM quiz_attempt WHERE user_id=${account.userId}`)).toBe('1')
    expect(sql(`SELECT COUNT(*) FROM quiz_draft WHERE user_id=${account.userId} AND quiz_id=${quiz.id}`)).toBe('0')
    expect(sql(`SELECT COUNT(*) FROM review_card WHERE user_id=${account.userId}`)).toBe('1')
    expect(sql(`SELECT COUNT(*) FROM learning_outcome_event WHERE user_id=${account.userId} AND event_type='quiz'`)).toBe('1')
    await expect(history.getByText('作答记录加载失败，请重试。', { exact: true })).toBeVisible()
    badHistory = false
    await history.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await history.getByRole('button', { name: /^0 \/ 100/ }).click()
    await expect(answer).toHaveValue('尚需巩固的答案')
    await expect(answer).toBeDisabled()
    await shot('quiz-reconciled-history.png')
  } finally {
    test.setTimeout(testInfo.timeout + 90000)
    if (!account && sql(`SELECT COUNT(*) FROM user WHERE username='${username}'`) === '1') account = await api(page.request, 'post', '/auth/login', { username, password })
    if (account) {
      cleanup ||= await request.newContext({ baseURL: testInfo.project.use.baseURL, storageState: await page.context().storageState(), timeout: 45000 })
      await page.close()
      try {
        await api(cleanup, 'delete', '/profile/account')
        await expect.poll(() => sql(`SELECT COUNT(*) FROM user WHERE id=${account.userId}`), { timeout: 60000, intervals: [1000] }).toBe('0')
        for (const table of ['knowledge_quiz', 'quiz_draft', 'quiz_attempt', 'review_card']) expect(sql(`SELECT COUNT(*) FROM ${table} WHERE user_id=${account.userId}`)).toBe('0')
      } finally { await cleanup.dispose() }
    }
  }
})
