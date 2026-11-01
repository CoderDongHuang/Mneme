import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import process from 'node:process'

test.skip(process.env.MNEME_REAL_E2E !== 'true', '需要真实 Gateway、Agent 和 MySQL')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('测验独立读取恢复，真实草稿和提交在历史故障后仍可刷新读取', async ({ page }, testInfo) => {
  test.setTimeout(180000)
  page.setDefaultTimeout(15000)
  let account, failList = true, failBases = true, failHistory = true, submits = 0
  async function api(method, path, data) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = await page.request[method]('/api/v1' + path, data === undefined ? {} : { data })
      if (response.status() === 429 && attempt < 2) {
        const seconds = Number(response.headers()['retry-after'])
        expect(seconds > 0 && seconds <= 60).toBe(true)
        await page.waitForTimeout(seconds * 1000 + 250); continue
      }
      expect(response.status(), `${method} ${path}`).toBe(200)
      const body = await response.json(); expect(body.code).toBe(200)
      return body.data
    }
    throw new Error('Rate limit did not recover')
  }
  const fail = route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 503, message: '读取服务暂不可用' }) })
  const shot = async name => {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(name), fullPage: false, animations: 'disabled' })
  }
  try {
    const suffix = randomUUID().replaceAll('-', '')
    account = await api('post', '/auth/register', { username: `quizstate_${suffix.slice(0, 10)}`, password: `Quiz!${suffix}` })
    // Use the supported import API to seed deterministic questions; grading,
    // draft persistence, submission and all successful reads use real services.
    await api('post', '/workspace/import', { version: 1, knowledge_bases: [{ id: 1, name: '测验状态真实资料库' }], quizzes: [1, 2].map(id => ({ id, kb_id: 1, title: `真实测验 ${id}`, topic: '状态回归', questions_json: JSON.stringify([{ type: 'short', prompt: `真实题目 ${id}`, answer: '原子持久化', key_points: ['持久化'], evidence: '持久化后的结果可以重新读取。' }]) })) })
    const quizzes = await api('get', '/workspace/quizzes')
    const quiz = quizzes.find(item => item.title === '真实测验 1')
    expect(quiz).toBeTruthy()
    await page.addInitScript(value => localStorage.setItem('mneme_auth', JSON.stringify(value)), account)
    await page.route('**/api/v1/workspace/quizzes', route => route.request().method() === 'GET' && failList ? fail(route) : route.continue())
    await page.route('**/api/v1/knowledge/base/list', route => route.request().method() === 'GET' && failBases ? fail(route) : route.continue())
    await page.route('**/api/v1/workspace/quizzes/*/attempts', route => route.request().method() === 'GET' && failHistory ? fail(route) : route.continue())
    page.on('response', response => { if (response.ok() && response.request().method() === 'POST' && /\/quizzes\/\d+\/submit$/.test(new URL(response.url()).pathname)) submits++ })
    await page.goto('/quiz')
    const list = page.getByRole('navigation', { name: '我的测验', exact: true })
    await expect(list.getByText('测验列表加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByText('还没有测验。', { exact: true })).toHaveCount(0)
    await expect(page.getByText('—', { exact: true })).toHaveCount(3)
    await shot('quiz-unavailable.png')
    await page.locator('.page-header').getByRole('button', { name: '创建测验', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '创建知识测验', exact: true })
    await expect(dialog.getByText('测验资料库加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await dialog.getByRole('textbox', { name: '测验主题', exact: true }).fill('保留主题')
    failBases = false
    await dialog.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(dialog.getByRole('combobox', { name: '资料库', exact: true })).not.toHaveValue('')
    await expect(dialog.getByRole('textbox', { name: '测验主题', exact: true })).toHaveValue('保留主题')
    await dialog.getByRole('button', { name: '关闭 / Close', exact: true }).click()
    failList = false
    await list.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await list.getByRole('button', { name: /^真实测验 1/ }).click()
    const history = page.getByRole('region', { name: '作答记录', exact: true })
    const answer = page.getByRole('textbox', { name: '你的答案', exact: true })
    await expect(history.getByText('作答记录加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    await answer.fill('可以恢复的持久化草稿')
    await expect.poll(async () => JSON.parse((await api('get', `/workspace/quizzes/${quiz.id}/draft`)).answers_json)).toEqual(['可以恢复的持久化草稿'])
    await list.getByRole('button', { name: /^真实测验 2/ }).click()
    await expect(page.getByRole('heading', { name: '真实题目 2', exact: true })).toBeVisible()
    await list.getByRole('button', { name: /^真实测验 1/ }).click()
    await expect(answer).toHaveValue('可以恢复的持久化草稿')
    await shot('quiz-draft-history-unavailable.png')
    await page.getByRole('button', { name: '提交测验（已答 1 题）', exact: true }).click()
    await expect(page.getByText(/本次原始得分 100/)).toBeVisible()
    await expect(answer).toBeDisabled()
    await expect(history.getByText('作答记录加载失败：读取服务暂不可用', { exact: true })).toBeVisible()
    expect(await api('get', `/workspace/quizzes/${quiz.id}/attempts`)).toHaveLength(1)
    failHistory = false
    await history.getByRole('button', { name: '重试 / Retry', exact: true }).click()
    await expect(history.getByRole('button', { name: /^100/ })).toBeVisible()
    await expect(page.getByText(/本次原始得分 100/)).toBeVisible()
    await shot('quiz-submitted-recovered.png')
    await page.reload()
    await list.getByRole('button', { name: /^真实测验 1/ }).click()
    await history.getByRole('button', { name: /^100/ }).click()
    await expect(answer).toHaveValue('可以恢复的持久化草稿')
    await expect(answer).toBeDisabled()
    expect(await api('get', `/workspace/quizzes/${quiz.id}/attempts`)).toHaveLength(1)
    expect(submits).toBe(1)
  } finally {
    if (account) await api('delete', '/profile/account')
  }
})
