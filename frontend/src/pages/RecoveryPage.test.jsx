import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import RecoveryPage from '../components/RecoveryDrill'
import { api } from '../api/client'
vi.mock('../api/client', () => ({ api: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
const history = () => within(screen.getByRole('region', { name: '演练历史' }))
const report = () => within(screen.getByRole('region', { name: '演练报告' }))
const runs = [{ id: 101, run_number: 11, created_at: '2026-11-02T00:00:00Z', status: 'queued' }, { id: 102, run_number: 12, status: 'in_progress' }]
const evidence = id => ({ run: { id, run_number: id, html_url: 'https://github.com/example/repo/actions/runs/' + id }, jobs: [{ id: 20, name: `report-${id}`, steps: [{ number: 1, name: 'verification', conclusion: 'success' }] }], artifacts: [] })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function unlock(token = 'a'.repeat(32)) {
  fireEvent.change(screen.getByLabelText('管理员凭证'), { target: { value: token } })
  fireEvent.click(screen.getByRole('button', { name: '验证权限' }))
}
function mockApi(action) {
  api.mockImplementation((path, options) => path.includes('/site') ? Promise.resolve({ jobs: [], archives: [] }) : action(path, options))
}

test('requires credential and explicit isolation confirmation before dispatch', async () => {
  mockApi((path, options) => Promise.resolve(options.method === 'POST' ? { status: 'accepted' } : { runs: [] }))
  render(<RecoveryPage />)
  expect(api).not.toHaveBeenCalled(); unlock()
  const button = await screen.findByRole('button', { name: '发起演练' })
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('确认语句'), { target: { value: 'ISOLATED DRILL' } })
  fireEvent.click(button)
  await screen.findByText('已提交隔离演练，请等待 GitHub 分配运行编号')
  expect(api).toHaveBeenCalledWith('/admin/recovery', expect.objectContaining({ method: 'POST', body: JSON.stringify({ confirmation: 'ISOLATED DRILL' }) }))
  fireEvent.click(screen.getByRole('button', { name: '锁定' }))
  expect(screen.queryByRole('button', { name: '发起演练' })).not.toBeInTheDocument()
  expect(screen.queryByText('已提交隔离演练，请等待 GitHub 分配运行编号')).not.toBeInTheDocument()
  unlock(); expect(screen.getByLabelText('确认语句')).toHaveValue('')
  await history().findByText('暂无演练历史')
})

test('initial failure is not empty history and an independent retry recovers', async () => {
  const pending = deferred(); let count = 0
  mockApi(() => ++count === 1 ? pending.promise : Promise.resolve({ runs: [] }))
  render(<RecoveryPage />); unlock()
  expect(history().getByText('正在读取演练历史')).toBeVisible()
  expect(screen.queryByText('暂无演练历史')).not.toBeInTheDocument()
  await act(async () => pending.reject(new Error('离线')))
  expect(history().getByText('演练历史加载失败：离线')).toBeVisible()
  expect(screen.queryByText('暂无演练历史')).not.toBeInTheDocument()
  fireEvent.click(history().getByRole('button', { name: '重试 / Retry' }))
  await history().findByText('暂无演练历史')
  expect(api.mock.calls.filter(([path]) => path.includes('/site'))).toHaveLength(1)
})

test('refresh failure declares cached history stale and serial refresh coalesces', async () => {
  const pending = deferred(); let count = 0
  mockApi(() => ++count === 1 ? Promise.resolve({ runs }) : count === 2 ? pending.promise : Promise.resolve({ runs: [] }))
  render(<RecoveryPage />); unlock()
  await history().findByText(/#11/)
  const refresh = screen.getByRole('button', { name: '刷新历史' })
  fireEvent.click(refresh); fireEvent.click(refresh); fireEvent.click(refresh)
  expect(count).toBe(2)
  await act(async () => pending.reject(new Error('断网')))
  await history().findByText('暂无演练历史')
  expect(count).toBe(3)
  mockApi(() => Promise.reject(new Error('断网')))
  fireEvent.click(refresh)
  await history().findByText('已有演练历史可能不是最新状态。')
  expect(history().queryByText('暂无演练历史')).not.toBeInTheDocument()
})

test.each([{}, { runs: null }, { runs: [null] }, { runs: [{ id: '101' }] }, { runs: [{ ...runs[0], status: {} }] }])('invalid history fails explicitly: %j', async payload => {
  mockApi(() => Promise.resolve(payload)); render(<RecoveryPage />); unlock()
  await history().findByText('演练历史加载失败：恢复演练响应格式不正确，请重试。')
  expect(history().queryByText('暂无演练历史')).not.toBeInTheDocument()
})

test('new report owns the result even when an aborted old read resolves late', async () => {
  const pending = deferred(); let oldSignal
  mockApi((path, options) => path.endsWith('/101') ? (oldSignal = options.signal, pending.promise) : Promise.resolve(path.endsWith('/102') ? evidence(102) : { runs }))
  render(<RecoveryPage />); unlock()
  await history().findByText(/#11/)
  fireEvent.click(history().getAllByRole('button', { name: '校验与报告' })[0])
  expect(report().getByText('正在读取演练报告')).toBeVisible()
  fireEvent.click(history().getAllByRole('button', { name: '校验与报告' })[1])
  await report().findByText('report-102')
  expect(oldSignal.aborted).toBe(true)
  await act(async () => pending.resolve(evidence(101)))
  expect(screen.queryByText('report-101')).not.toBeInTheDocument()
})

test('invalid or failed report clears previous content and retries only the selected report', async () => {
  let count = 0, historyReads = 0
  mockApi(path => path.endsWith('/101') ? Promise.resolve(++count === 2 ? { ...evidence(101), jobs: [{}] } : evidence(101)) : (historyReads++, Promise.resolve({ runs })))
  render(<RecoveryPage />); unlock(); await history().findByText(/#11/)
  const button = history().getAllByRole('button', { name: '校验与报告' })[0]
  fireEvent.click(button); await report().findByText('report-101')
  fireEvent.click(button)
  await report().findByText('演练报告加载失败：恢复演练响应格式不正确，请重试。')
  expect(screen.queryByText('report-101')).not.toBeInTheDocument()
  fireEvent.click(report().getByRole('button', { name: '重试 / Retry' }))
  await report().findByText('report-101'); expect(historyReads).toBe(1)
})

test('lock aborts history, reports and POST; late results never enter new credential scope', async () => {
  const detail = deferred(), post = deferred(), read = deferred(); const signals = []; let reads = 0
  mockApi((path, options) => {
    signals.push(options.signal)
    if (options.headers['X-Admin-Token'] === 'b'.repeat(32)) return Promise.resolve({ runs: [] })
    if (options.method === 'POST') return post.promise
    if (path.endsWith('/101')) return detail.promise
    return ++reads === 1 ? Promise.resolve({ runs }) : read.promise
  })
  render(<RecoveryPage />); unlock(); await history().findByText(/#11/)
  fireEvent.click(history().getAllByRole('button', { name: '校验与报告' })[0])
  fireEvent.click(screen.getByRole('button', { name: '刷新历史' }))
  fireEvent.change(screen.getByLabelText('确认语句'), { target: { value: 'ISOLATED DRILL' } })
  fireEvent.submit(screen.getByLabelText('确认语句').closest('form'))
  expect(screen.getByLabelText('确认语句')).toBeDisabled()
  fireEvent.submit(screen.getByLabelText('确认语句').closest('form'))
  expect(api.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '锁定' }))
  expect(signals.every(signal => signal.aborted)).toBe(true)
  unlock('b'.repeat(32)); await history().findByText('暂无演练历史')
  await act(async () => { detail.resolve(evidence(101)); post.resolve({ status: 'accepted' }); read.resolve({ runs }) })
  expect(screen.queryByText('report-101')).not.toBeInTheDocument()
  expect(screen.queryByText(/#11/)).not.toBeInTheDocument()
  expect(screen.queryByText('已提交隔离演练，请等待 GitHub 分配运行编号')).not.toBeInTheDocument()
})

test('accepted dispatch is preserved when its following history refresh fails', async () => {
  let reads = 0
  mockApi((path, options) => options.method === 'POST' ? Promise.resolve({ status: 'accepted' }) : ++reads === 1 ? Promise.resolve({ runs: [] }) : Promise.reject(new Error('历史故障')))
  render(<RecoveryPage />); unlock(); await history().findByText('暂无演练历史')
  fireEvent.change(screen.getByLabelText('确认语句'), { target: { value: 'ISOLATED DRILL' } })
  fireEvent.click(screen.getByRole('button', { name: '发起演练' }))
  await screen.findByText('已提交隔离演练，请等待 GitHub 分配运行编号')
  await history().findByText('演练历史加载失败：历史故障')
  expect(screen.getByLabelText('确认语句')).toHaveValue('')
})

test('ambiguous dispatch never retries POST automatically or claims completion', async () => {
  mockApi((path, options) => options.method === 'POST' ? Promise.reject(new Error('断网')) : Promise.resolve({ runs: [] }))
  render(<RecoveryPage />); unlock(); await history().findByText('暂无演练历史')
  fireEvent.change(screen.getByLabelText('确认语句'), { target: { value: 'ISOLATED DRILL' } })
  fireEvent.click(screen.getByRole('button', { name: '发起演练' }))
  await screen.findByText('演练提交未确认：断网。请先刷新历史核实，避免重复提交。')
  expect(screen.getByLabelText('确认语句')).toHaveValue('ISOLATED DRILL')
  expect(api.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1)
})

test('revoked permission clears cached history and reports', async () => {
  let fail = false
  mockApi(path => fail ? Promise.reject(Object.assign(new Error('无权限'), { status: 403 })) : Promise.resolve(path.endsWith('/101') ? evidence(101) : { runs }))
  render(<RecoveryPage />); unlock(); await history().findByText(/#11/)
  fireEvent.click(history().getAllByRole('button', { name: '校验与报告' })[0]); await report().findByText('report-101')
  fail = true; fireEvent.click(screen.getByRole('button', { name: '刷新历史' }))
  await waitFor(() => expect(screen.queryByText('report-101')).not.toBeInTheDocument())
  expect(screen.queryByText(/#11/)).not.toBeInTheDocument()
  expect(history().getByText('演练历史加载失败：无权限')).toBeVisible()
})
