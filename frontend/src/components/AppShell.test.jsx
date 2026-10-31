import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import AppShell from './AppShell'
import AdminRoute from './AdminRoute'
import { setLanguage } from '../i18n'

const auth = vi.hoisted(() => ({ session: { username: 'tester' }, isAdmin: false, logout: vi.fn() }))
vi.mock('../state/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../state/PreferencesContext', () => ({ usePreferences: () => ({ preferences: { theme: 'light' }, save: vi.fn() }) }))

afterEach(async () => { auth.isAdmin = false; await setLanguage('zh-CN') })

function show(path = '/tasks') {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route element={<AppShell />}>
      <Route path="/tasks" element={<h1>Tasks content</h1>} />
      <Route path="/settings" element={<h1>Settings content</h1>} />
      <Route path="/legal/:document" element={<h1>Legal content</h1>} />
      <Route element={<AdminRoute />}><Route path="/operations" element={<h1>Admin content</h1>} /></Route>
    </Route>
  </Routes></MemoryRouter>)
}

test('ordinary users get all personal routes in explicit groups without administrator links', async () => {
  show()
  const nav = within(screen.getByRole('navigation', { name: '主要导航' }))
  expect(nav.getAllByRole('heading').map(node => node.textContent)).toEqual(['学习空间', '工作空间', '账户与设置'])
  expect(nav.getAllByRole('link')).toHaveLength(13)
  expect(within(nav.getByRole('region', { name: '工作空间' })).getAllByRole('link').map(node => node.getAttribute('href'))).toEqual(['/workspace', '/tasks'])
  expect(within(nav.getByRole('region', { name: '账户与设置' })).getAllByRole('link').map(node => node.getAttribute('href'))).toEqual(['/profile', '/legal/terms', '/recovery', '/privacy', '/settings'])
  expect(nav.queryByRole('region', { name: '管理', exact: true })).not.toBeInTheDocument()
  expect(document.querySelector('.reference-topbar')).toHaveTextContent('工作空间/任务中心')
  await userEvent.click(nav.getByRole('link', { name: '设置', exact: true }))
  expect(await screen.findByRole('heading', { name: 'Settings content' })).toBeVisible()
  expect(document.querySelector('.reference-topbar')).toHaveTextContent('账户与设置/设置')
  expect(screen.getByRole('main')).toHaveFocus()
})

test('administrator navigation keeps personal settings separate and opens the guarded admin route', async () => {
  auth.isAdmin = true
  show()
  const admin = within(screen.getByRole('region', { name: '管理', exact: true }))
  expect(admin.getAllByRole('link')).toHaveLength(1)
  await userEvent.click(admin.getByRole('link', { name: '管理员运维' }))
  expect(await screen.findByRole('heading', { name: 'Admin content' })).toBeVisible()
  expect(document.querySelector('.reference-topbar')).toHaveTextContent('管理/管理员运维')
})

test('direct administrator URL remains guarded for ordinary users', () => {
  show('/operations')
  expect(screen.queryByRole('heading', { name: 'Admin content' })).not.toBeInTheDocument()
  expect(screen.getByRole('alert')).toBeVisible()
})

test('legal subroutes and English navigation keep the correct account grouping', async () => {
  await setLanguage('en')
  show('/legal/privacy')
  expect(screen.getByRole('region', { name: 'Account and settings' })).toBeVisible()
  expect(document.querySelector('.reference-topbar')).toHaveTextContent('Account and settings')
  expect(screen.queryByRole('heading', { name: '工作空间' })).not.toBeInTheDocument()
})
