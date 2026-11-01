import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import MemoryPage from './MemoryPage'
import { endpoints } from '../api/client'

vi.mock('../api/client', () => ({ endpoints: {
  managedMemories: vi.fn(), pendingMemories: vi.fn(), memoryVersions: vi.fn(),
  updateManagedMemory: vi.fn(), restoreMemory: vi.fn(), confirmMemory: vi.fn(), writeMemory: vi.fn(),
} }))
const first = { id: 'a', category: 'preference', topic: '第一条', content: '内容一', status: 'active', tags: [] }
const second = { ...first, id: 'b', topic: '第二条', content: '内容二' }
const pending = { memoryId: 'p', category: 'preference', topic: '待确认主题', content: '待确认内容' }
beforeEach(() => {
  vi.resetAllMocks()
  endpoints.managedMemories.mockResolvedValue({ memories: [first, second] })
  endpoints.pendingMemories.mockResolvedValue([])
  endpoints.memoryVersions.mockResolvedValue({ versions: [] })
})
function mount() { return render(<MemoryRouter><MemoryPage /></MemoryRouter>) }
function metric(name) { return within(document.querySelector('.reference-metrics')).getByText(name).parentElement.querySelector('strong') }
function detail() { return screen.getByRole('complementary', { name: '记忆详情' }) }
function openHistory() { fireEvent.click(within(detail()).getByText(/^历史版本/)) }

test('initial failure never invents zero metrics, empty records or a version count; retry recovers a real empty result', async () => {
  endpoints.managedMemories.mockRejectedValueOnce(new Error('offline'))
  endpoints.pendingMemories.mockRejectedValueOnce(new Error('offline'))
  mount()
  expect(screen.getByRole('status')).toHaveTextContent('正在读取记忆')
  await screen.findByText('记忆列表加载失败，请重试。')
  expect(screen.getByText('待确认记忆加载失败，请重试。')).toBeVisible()
  for (const name of ['总记忆数', '待确认', '已掌握', '需巩固']) expect(metric(name)).toHaveTextContent('—')
  expect(screen.queryByText('暂无符合条件的记忆')).not.toBeInTheDocument()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  endpoints.managedMemories.mockResolvedValueOnce({ memories: [] })
  fireEvent.click(screen.getByRole('button', { name: '刷新记忆' }))
  await screen.findByText('暂无符合条件的记忆')
  expect(metric('总记忆数')).toHaveTextContent('0')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('partial failure keeps successful records and unknown pending count; refresh failure retains data and the unsaved detail draft', async () => {
  endpoints.pendingMemories.mockRejectedValueOnce(new Error('offline'))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /第一条/ }))
  expect(metric('总记忆数')).toHaveTextContent('2')
  expect(metric('待确认')).toHaveTextContent('—')
  fireEvent.change(within(detail()).getByLabelText('内容'), { target: { value: '未保存草稿' } })
  endpoints.managedMemories.mockRejectedValueOnce(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: '刷新记忆' }))
  await screen.findByText('已有记忆记录可能不是最新状态。')
  expect(screen.getByRole('button', { name: /第一条/ })).toBeVisible()
  expect(within(detail()).getByLabelText('内容')).toHaveValue('未保存草稿')
  expect(metric('待确认')).toHaveTextContent('0')
  expect(screen.queryByText('暂无符合条件的记忆')).not.toBeInTheDocument()
})

test('version failure is distinct from no history, retries locally and ignores a previous selection late response', async () => {
  let release
  endpoints.memoryVersions.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
    .mockRejectedValueOnce(new Error('offline'))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /第一条/ }))
  fireEvent.click(screen.getByRole('button', { name: /第二条/ }))
  openHistory()
  await within(detail()).findByText('记忆版本加载失败，请重试。')
  expect(within(detail()).queryByText('暂无历史版本。')).not.toBeInTheDocument()
  expect(within(detail()).getByText('历史版本', { exact: true })).toBeVisible()
  await act(async () => release({ versions: [{ version: 9, content: '旧选择的秘密' }] }))
  expect(detail()).not.toHaveTextContent('旧选择的秘密')
  fireEvent.click(within(detail()).getByRole('button', { name: '重试 / Retry' }))
  await within(detail()).findByText('暂无历史版本。')
  expect(endpoints.managedMemories).toHaveBeenCalledTimes(1)
})

test('save receipt survives a failed version refresh and cannot be mistaken for a failed write', async () => {
  endpoints.memoryVersions.mockResolvedValueOnce({ versions: [{ version: 1, content: '原内容' }] }).mockRejectedValueOnce(new Error('offline'))
  endpoints.updateManagedMemory.mockResolvedValueOnce({ memories: [{ ...first, content: '已保存内容' }, second] })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /第一条/ }))
  openHistory()
  await within(detail()).findByText('原内容')
  fireEvent.change(within(detail()).getByLabelText('内容'), { target: { value: '已保存内容' } })
  fireEvent.click(within(detail()).getByRole('button', { name: '保存修改' }))
  await within(detail()).findByText('记忆版本加载失败，请重试。')
  expect(within(detail()).getByText('记忆已保存，检索缓存已更新')).toBeVisible()
  expect(within(detail()).getByText('已有版本记录可能不是最新状态。')).toBeVisible()
  expect(within(detail()).getByRole('button', { name: '恢复此版本' })).toBeDisabled()
  expect(endpoints.updateManagedMemory).toHaveBeenCalledTimes(1)
})

test('successful confirmation remains visible when refresh fails and the consumed candidate does not reappear', async () => {
  endpoints.pendingMemories.mockResolvedValueOnce([pending]).mockRejectedValueOnce(new Error('offline'))
  endpoints.confirmMemory.mockResolvedValueOnce({})
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '确认记住' }))
  await screen.findByText('待确认记忆加载失败，请重试。')
  expect(screen.getByText('记忆已确认')).toBeVisible()
  expect(screen.queryByRole('button', { name: '确认记住' })).not.toBeInTheDocument()
  expect(screen.getByText('已有待确认记录可能不是最新状态。')).toBeVisible()
  expect(screen.queryByText('暂无符合条件的记忆')).not.toBeInTheDocument()
  expect(endpoints.confirmMemory).toHaveBeenCalledOnce()
})

test('an older refresh cannot overwrite a saved record and selection is locked during the write', async () => {
  let finishRefresh, finishSave
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /第一条/ }))
  endpoints.managedMemories.mockReturnValueOnce(new Promise(resolve => { finishRefresh = resolve }))
  endpoints.updateManagedMemory.mockReturnValueOnce(new Promise(resolve => { finishSave = resolve }))
  fireEvent.click(screen.getByRole('button', { name: '刷新记忆' }))
  fireEvent.change(within(detail()).getByLabelText('内容'), { target: { value: '最新保存内容' } })
  fireEvent.click(within(detail()).getByRole('button', { name: '保存修改' }))
  expect(screen.getByRole('button', { name: /第二条/ })).toBeDisabled()
  await act(async () => finishSave({ memories: [{ ...first, content: '最新保存内容' }, second] }))
  await act(async () => finishRefresh({ memories: [first, second] }))
  expect(within(detail()).getByLabelText('内容')).toHaveValue('最新保存内容')
  expect(screen.getByRole('button', { name: /第一条 最新保存内容/ })).toBeVisible()
  expect(screen.getByRole('button', { name: /第二条/ })).toBeEnabled()
})

test('unmounted list replies cannot affect a new page', async () => {
  endpoints.pendingMemories.mockRejectedValueOnce(new Error('offline'))
  const view = mount()
  await screen.findByText('待确认记忆加载失败，请重试。')
  let release
  endpoints.managedMemories.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  fireEvent.click(screen.getByRole('button', { name: '刷新记忆' }))
  view.unmount()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /第一条/ }))
  await act(async () => release({ memories: [] }))
  expect(screen.getByRole('button', { name: /第一条/ })).toBeVisible()
  expect(metric('总记忆数')).toHaveTextContent('2')
  await waitFor(() => expect(endpoints.managedMemories).toHaveBeenCalledTimes(3))
})

test('unmounted version replies cannot affect a new detail selection', async () => {
  let release
  endpoints.memoryVersions.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
  const view = mount()
  fireEvent.click(await screen.findByRole('button', { name: /第一条/ }))
  view.unmount()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /第二条/ }))
  openHistory()
  await within(detail()).findByText('暂无历史版本。')
  await act(async () => release({ versions: [{ version: 12, content: '卸载后的旧内容' }] }))
  expect(detail()).not.toHaveTextContent('卸载后的旧内容')
})
