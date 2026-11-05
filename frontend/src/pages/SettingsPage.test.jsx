import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import SettingsPage from './SettingsPage'
import { endpoints } from '../api/client'

const owner = vi.hoisted(() => ({ session: { userId: 1 } }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => owner }))
vi.mock('../api/client', () => ({ endpoints: { modelSettings: vi.fn(), healthConfig: vi.fn(), checkProviders: vi.fn(), saveModelSettings: vi.fn(), testModelSettings: vi.fn() } }))
beforeEach(() => {
  vi.resetAllMocks()
  owner.session = { userId: 1 }
  endpoints.modelSettings.mockResolvedValue({ provider: 'deepseek', model: 'deepseek-chat', enabled: false })
  endpoints.healthConfig.mockResolvedValue({ service: 'mneme-python-agent' })
})

test('an unavailable health response is never shown as connected', async () => {
  endpoints.healthConfig.mockResolvedValue({ status: 'unavailable', storage: { backend: 'local' } })
  render(<SettingsPage />)
  expect(await screen.findByText('服务状态暂不可用')).toBeVisible()
  expect(screen.queryByText('服务已连接')).not.toBeInTheDocument()
  expect(screen.getByText('本地存储')).toBeVisible()
})

test('loading and failed refresh do not leave a stale connected status', async () => {
  let resolveHealth
  endpoints.healthConfig.mockReturnValueOnce(new Promise(resolve => { resolveHealth = resolve }))
  render(<SettingsPage />)
  expect(within(screen.getByRole('complementary', { name: '运行状态' })).getByRole('status')).toHaveTextContent('加载中...')
  expect(screen.getByRole('button', { name: '刷新状态' })).toBeDisabled()
  await act(async () => resolveHealth({ service: 'mneme-python-agent' }))
  expect(screen.getByText('服务已连接')).toBeVisible()
  endpoints.healthConfig.mockRejectedValueOnce(new Error('连接中断'))
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  expect(await screen.findByText('服务状态暂不可用')).toBeVisible()
  expect(screen.queryByText('服务已连接')).not.toBeInTheDocument()
})

test('model and health failures retry independently without a false empty form', async () => {
  endpoints.modelSettings.mockRejectedValueOnce(new Error('配置断开'))
  endpoints.healthConfig.mockRejectedValueOnce(new Error('状态断开'))
  render(<SettingsPage />)
  expect(screen.getByText('正在读取模型配置…')).toBeVisible()
  expect(await screen.findByText('模型配置加载失败：配置断开')).toBeVisible()
  expect(await screen.findByText('服务状态加载失败，请重试。')).toBeVisible()
  expect(screen.queryByRole('form', { name: '个人模型服务' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重试 / Retry' }))
  expect(await screen.findByLabelText('模型名称')).toHaveValue('deepseek-chat')
  expect(endpoints.healthConfig).toHaveBeenCalledTimes(1)
  fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'draft-model' } })
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  expect(await screen.findByText('服务已连接')).toBeVisible()
  expect(screen.getByLabelText('模型名称')).toHaveValue('draft-model')
  expect(endpoints.modelSettings).toHaveBeenCalledTimes(2)
})

test('save locks all fields and duplicate submissions, clears key only after success, and preserves receipt across health failure', async () => {
  let complete
  endpoints.saveModelSettings.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
  render(<SettingsPage />)
  const form = await screen.findByRole('form', { name: '个人模型服务' })
  fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'unit-secret' } })
  fireEvent.submit(form); fireEvent.submit(form)
  expect(endpoints.saveModelSettings).toHaveBeenCalledTimes(1)
  for (const control of form.querySelectorAll('input,select,button')) expect(control).toBeDisabled()
  endpoints.healthConfig.mockRejectedValueOnce(new Error('状态断开'))
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  await act(async () => complete({ provider: 'deepseek', model: 'deepseek-chat', enabled: false, hasKey: true, keyMask: 'masked' }))
  expect(await screen.findByText('模型配置已保存')).toBeVisible()
  expect(await screen.findByText('服务状态加载失败，请重试。')).toBeVisible()
  expect(screen.getByLabelText('API 密钥')).toHaveValue('')
  expect(screen.getByRole('button', { name: '保存配置' })).toBeEnabled()
})

test('failed save retains draft and permits an explicit retry without rereading', async () => {
  endpoints.saveModelSettings.mockRejectedValueOnce(Object.assign(new Error('写入失败'), { status: 400 })).mockResolvedValueOnce({ provider: 'deepseek', model: 'draft-model', enabled: false })
  render(<SettingsPage />)
  fireEvent.change(await screen.findByLabelText('模型名称'), { target: { value: 'draft-model' } })
  fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'unit-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  expect(await screen.findByText('写入失败')).toBeVisible()
  expect(screen.getByLabelText('模型名称')).toHaveValue('draft-model')
  expect(screen.getByLabelText('API 密钥')).toHaveValue('unit-secret')
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  expect(await screen.findByText('模型配置已保存')).toBeVisible()
  expect(endpoints.modelSettings).toHaveBeenCalledTimes(1)
  expect(endpoints.saveModelSettings.mock.calls[1][0]).toMatchObject({ model: 'draft-model', apiKey: 'unit-secret' })
})

test('test result belongs to the current draft and fields lock until the probe ends', async () => {
  let complete
  endpoints.testModelSettings.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
  render(<SettingsPage />)
  await screen.findByLabelText('模型名称')
  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  expect(screen.getByLabelText('模型名称')).toBeDisabled()
  await act(async () => complete({ model: 'deepseek-chat', latency_ms: 3 }))
  expect(screen.getByText('实际模型调用通过')).toBeVisible()
  fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'another-model' } })
  expect(screen.queryByText('实际模型调用通过')).not.toBeInTheDocument()
  expect(screen.queryByText('模型连接测试通过，配置尚未保存')).not.toBeInTheDocument()
})

test('unmount aborts reads and an old save cannot affect a newly mounted settings page', async () => {
  let complete
  endpoints.saveModelSettings.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
  const old = render(<SettingsPage />)
  await screen.findByLabelText('模型名称')
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  const options = endpoints.saveModelSettings.mock.calls[0][1]
  old.unmount()
  expect(options.signal.aborted).toBe(true)
  render(<SettingsPage />)
  await screen.findByLabelText('模型名称')
  await act(async () => complete({ provider: 'deepseek', model: 'old-model', enabled: false }))
  expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-chat')
  expect(screen.queryByText('模型配置已保存')).not.toBeInTheDocument()
})

test('malformed model responses are an explicit retryable error', async () => {
  endpoints.modelSettings.mockResolvedValueOnce(null)
  render(<SettingsPage />)
  expect(await screen.findByText('模型配置加载失败：模型配置响应格式不正确')).toBeVisible()
  expect(screen.queryByLabelText('模型名称')).not.toBeInTheDocument()
})

test('shared probes distinguish working, disabled and failing services and clear stale results on error', async () => {
  endpoints.healthConfig.mockResolvedValue({ service: 'mneme-python-agent' })
  endpoints.checkProviders.mockResolvedValueOnce({ results: { chat: { state: 'ok', latency_ms: 50 }, embedding: { state: 'authentication_failed', latency_ms: 20 }, rerank: { state: 'disabled', latency_ms: 0 }, ocr: { state: 'runtime_missing', latency_ms: 1 } } })
  render(<SettingsPage />)
  fireEvent.click(screen.getByRole('button', { name: '检测连通性' }))
  const results = await screen.findByRole('status', { name: '共享服务检测结果' })
  expect(results).toHaveTextContent('连接正常')
  expect(results).toHaveTextContent('密钥验证失败')
  expect(results).toHaveTextContent('未启用')
  expect(results).toHaveTextContent('运行依赖缺失')
  endpoints.checkProviders.mockRejectedValueOnce(new Error('检测连接中断'))
  fireEvent.click(screen.getByRole('button', { name: '检测连通性' }))
  expect(await screen.findByText('检测连接中断')).toBeVisible()
  expect(screen.queryByRole('status', { name: '共享服务检测结果' })).not.toBeInTheDocument()
})

test.each([{}, { demo_mode: 'false', service: 'mneme-python-agent' }, { service: 'mneme-python-agent', storage: { backend: {} } }])('invalid health fields never imply a connected service: %j', async value => {
  endpoints.healthConfig.mockResolvedValueOnce(value)
  render(<SettingsPage />)
  expect(await screen.findByText('服务状态加载失败，请重试。')).toBeVisible()
  expect(screen.queryByText('服务已连接')).not.toBeInTheDocument()
})

test.each([{ hasKey: 'false' }, { keyMask: {} }, { apiKey: 'must-not-echo' }])('invalid model metadata cannot create an editable form: %j', async fields => {
  endpoints.modelSettings.mockResolvedValueOnce({ provider: 'deepseek', model: 'deepseek-chat', enabled: false, ...fields })
  render(<SettingsPage />)
  expect(await screen.findByText('模型配置加载失败：模型配置响应格式不正确')).toBeVisible()
  expect(screen.queryByLabelText('模型名称')).not.toBeInTheDocument()
})

test('a malformed save receipt retains drafts, locks writes and reconciles with GET only', async () => {
  endpoints.saveModelSettings.mockResolvedValueOnce({ provider: 'deepseek', model: {}, enabled: false })
  render(<SettingsPage />)
  fireEvent.change(await screen.findByLabelText('模型名称'), { target: { value: 'kept-model' } })
  fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'kept-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  expect(await screen.findByText('模型保存结果尚未确认，请先核对服务端配置。')).toBeVisible()
  expect(screen.getByLabelText('模型名称')).toHaveValue('kept-model')
  expect(screen.getByLabelText('API 密钥')).toHaveValue('kept-secret')
  expect(screen.getByRole('button', { name: '保存配置' })).toBeDisabled()
  expect(screen.queryByText('模型配置已保存')).not.toBeInTheDocument()
  endpoints.modelSettings.mockRejectedValueOnce(new Error('read failed'))
  fireEvent.click(screen.getByRole('button', { name: '核对已保存模型配置' }))
  expect(await screen.findByText('模型配置加载失败：read failed')).toBeVisible()
  expect(screen.queryByRole('button', { name: '采用服务端配置' })).not.toBeInTheDocument()
  endpoints.modelSettings.mockResolvedValueOnce({ provider: 'deepseek', model: 'saved-model', enabled: false })
  fireEvent.click(screen.getByRole('button', { name: '核对已保存模型配置' }))
  expect(await screen.findByText('saved-model', { exact: true })).toBeVisible()
  expect(endpoints.saveModelSettings).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: '保留草稿，继续编辑' }))
  expect(screen.getByLabelText('模型名称')).toHaveValue('kept-model')
  expect(screen.getByLabelText('API 密钥')).toHaveValue('kept-secret')
  expect(screen.getByRole('button', { name: '保存配置' })).toBeEnabled()
})

test('unknown save can adopt a verified server configuration and clear the typed key', async () => {
  endpoints.saveModelSettings.mockRejectedValueOnce(new Error('connection lost'))
  render(<SettingsPage />)
  fireEvent.change(await screen.findByLabelText('API 密钥'), { target: { value: 'typed-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  expect(await screen.findByRole('button', { name: '核对已保存模型配置' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: '核对已保存模型配置' }))
  fireEvent.click(await screen.findByRole('button', { name: '采用服务端配置' }))
  expect(screen.getByLabelText('API 密钥')).toHaveValue('')
  expect(screen.getByRole('button', { name: '保存配置' })).toBeEnabled()
  expect(endpoints.saveModelSettings).toHaveBeenCalledTimes(1)
})

test.each([null, { model: {}, latency_ms: 1 }, { model: 'deepseek-chat', latency_ms: -1 }])('invalid personal probe is not a success: %j', async value => {
  endpoints.testModelSettings.mockResolvedValueOnce(value)
  render(<SettingsPage />)
  await screen.findByLabelText('模型名称')
  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  expect(await screen.findByText('模型测试响应格式不正确，请核实后再试。')).toBeVisible()
  expect(screen.queryByText('实际模型调用通过')).not.toBeInTheDocument()
})

test.each([{}, { results: { chat: { state: 'ok', latency_ms: {} } } }])('invalid shared probes do not render success: %j', async value => {
  endpoints.checkProviders.mockResolvedValueOnce(value)
  render(<SettingsPage />)
  fireEvent.click(screen.getByRole('button', { name: '检测连通性' }))
  expect(await screen.findByText('共享服务检测响应格式不正确，请核实后再试。')).toBeVisible()
  expect(screen.queryByRole('status', { name: '共享服务检测结果' })).not.toBeInTheDocument()
})

test('a valid but unrelated save receipt cannot replace the current draft', async () => {
  endpoints.saveModelSettings.mockResolvedValueOnce({ provider: 'deepseek', model: 'other-model', enabled: false })
  render(<SettingsPage />)
  await screen.findByLabelText('模型名称')
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  expect(await screen.findByText('模型保存结果尚未确认，请先核对服务端配置。')).toBeVisible()
  expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-chat')
})

test('switching account cancels old saves and isolates drafts, diagnostics and late responses', async () => {
  let complete
  endpoints.saveModelSettings.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
  const view = render(<SettingsPage />)
  fireEvent.change(await screen.findByLabelText('模型名称'), { target: { value: 'private-model' } })
  fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'private-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  const signal = endpoints.saveModelSettings.mock.calls[0][1].signal
  owner.session = { userId: 2 }
  view.rerender(<SettingsPage />)
  expect(signal.aborted).toBe(true)
  expect(await screen.findByLabelText('模型名称')).toHaveValue('deepseek-chat')
  await act(async () => complete({ provider: 'deepseek', model: 'private-model', enabled: false }))
  expect(screen.getByLabelText('API 密钥')).toHaveValue('')
  expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-chat')
  expect(screen.queryByText('模型配置已保存')).not.toBeInTheDocument()
})

test('old health and reconciliation reads cannot update another account', async () => {
  let read, health
  endpoints.saveModelSettings.mockRejectedValueOnce(Object.assign(new Error('unknown'), { status: 500 }))
  const view = render(<SettingsPage />)
  await screen.findByLabelText('模型名称')
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await screen.findByText('模型保存结果尚未确认，请先核对服务端配置。')
  endpoints.modelSettings.mockReturnValueOnce(new Promise(resolve => { read = resolve }))
  endpoints.healthConfig.mockReturnValueOnce(new Promise(resolve => { health = resolve }))
  fireEvent.click(screen.getByRole('button', { name: '核对已保存模型配置' }))
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  const modelSignal = endpoints.modelSettings.mock.calls[1][0].signal
  const healthSignal = endpoints.healthConfig.mock.calls[1][0].signal
  owner.session = { userId: 2 }
  view.rerender(<SettingsPage />)
  expect(modelSignal.aborted).toBe(true); expect(healthSignal.aborted).toBe(true)
  await screen.findByLabelText('模型名称')
  await act(async () => {
    read({ provider: 'deepseek', model: 'private-model', enabled: false })
    health({ status: 'unavailable' })
  })
  expect(screen.getByText('服务已连接')).toBeVisible()
  expect(screen.queryByRole('button', { name: '采用服务端配置' })).not.toBeInTheDocument()
  expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-chat')
})
