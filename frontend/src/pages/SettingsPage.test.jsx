import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import SettingsPage from './SettingsPage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: { modelSettings: vi.fn(), healthConfig: vi.fn(), checkProviders: vi.fn() } }))
beforeEach(() => {
  endpoints.modelSettings.mockResolvedValue({ provider: 'deepseek', model: 'deepseek-chat', enabled: false })
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
  expect(screen.getByRole('status')).toHaveTextContent('加载中...')
  expect(screen.getByRole('button', { name: '刷新状态' })).toBeDisabled()
  await act(async () => resolveHealth({ service: 'mneme-python-agent' }))
  expect(screen.getByText('服务已连接')).toBeVisible()
  endpoints.healthConfig.mockRejectedValueOnce(new Error('连接中断'))
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  expect(await screen.findByText('服务状态暂不可用')).toBeVisible()
  expect(screen.queryByText('服务已连接')).not.toBeInTheDocument()
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
