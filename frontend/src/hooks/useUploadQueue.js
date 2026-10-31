import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'

function load(key) {
  try {
    const items = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(items) ? items.slice(-40).map(item => {
      if (item.status === 'pending') return { ...item, status: 'cancelled', message: '等待项已取消，请重新选择文件' }
      if (['uploading', 'cancelling'].includes(item.status)) return { ...item, status: 'uncertain', message: '上传结果待确认，请核实服务端状态' }
      return item
    }) : []
  } catch { return [] }
}

function createScope(key) {
  return { key, queue: load(key), locked: false, files: new Map(), controllers: new Map(), cancelled: new Set() }
}

function persist(scope, changed, expected = new Map()) {
  try {
    const stored = JSON.parse(localStorage.getItem(scope.key) || '[]')
    const items = new Map((Array.isArray(stored) ? stored : []).map(item => [item.id, item]))
    for (const item of changed) {
      const previous = items.get(item.id)
      // A late response must not replace a newer retry of the same queue entry.
      if (!previous || !previous.requestId || previous.requestId === item.requestId
        || previous.requestId === expected.get(item.id)?.requestId) items.set(item.id, item)
    }
    localStorage.setItem(scope.key, JSON.stringify([...items.values()].slice(-40)))
  } catch { /* memory queue remains usable */ }
}

export default function useUploadQueue(storageKey, onSubmitted) {
  const [queue, setQueue] = useState(() => load(storageKey))
  const [uploading, setUploading] = useState(false)
  const current = useRef(null)
  const mounted = useRef(false)
  const callback = useRef(onSubmitted)
  useEffect(() => { callback.current = onSubmitted }, [onSubmitted])
  useEffect(() => {
    const scope = createScope(storageKey)
    current.current = scope
    mounted.current = true
    setQueue(scope.queue)
    setUploading(false)
    return () => {
      mounted.current = false
      // Navigation keeps the in-flight request and its receipt, but does not
      // start pending files. Switching libraries does not change storageKey.
      const waiting = scope.queue.filter(item => item.status === 'pending')
      scope.queue = scope.queue.map(item => item.status === 'pending'
        ? { ...item, status: 'cancelled', message: '已离开页面，等待项已取消' } : item)
      persist(scope, scope.queue.filter(item => waiting.some(previous => previous.id === item.id)))
      scope.files.forEach((_, id) => { if (!scope.controllers.has(id)) scope.files.delete(id) })
    }
  }, [storageKey])

  function update(scope, change) {
    const previous = new Map(scope.queue.map(item => [item.id, item]))
    scope.queue = change(scope.queue)
    persist(scope, scope.queue.filter(item => previous.get(item.id) !== item), previous)
    if (mounted.current && current.current === scope) setQueue(scope.queue)
  }
  const patch = (scope, id, values) => update(scope, items => items.map(item => item.id === id ? { ...item, ...values } : item))
  function submitted(scope, entry, document) {
    patch(scope, entry.id, { status: 'submitted', message: '已提交，解析取消请到任务中心', documentId: document.id, taskId: document.parseTaskId })
    scope.files.delete(entry.id)
    if (mounted.current && current.current === scope) callback.current(entry.kbId, { fileName: entry.name, ...document })
  }
  async function confirm(scope, entry, error) {
    try {
      const receipt = await endpoints.cancelUpload(entry.kbId, entry.requestId || entry.id)
      if (receipt.status === 'submitted') {
        submitted(scope, entry, { id: receipt.document_id, parseTaskId: receipt.task_id, status: 'parsing' })
      } else if (receipt.status === 'cancelled') {
        const cancelled = scope.cancelled.has(entry.id) || !error
        patch(scope, entry.id, { status: cancelled ? 'cancelled' : 'failed', message: cancelled ? '已取消上传' : error.message })
        if (cancelled) scope.files.delete(entry.id)
      } else throw new Error('Invalid upload receipt')
    } catch {
      patch(scope, entry.id, { status: 'uncertain', message: '上传结果待确认，请核实服务端状态' })
    }
  }
  async function submit(scope, entries) {
    if (scope.locked || !entries.length) return
    scope.locked = true
    setUploading(true)
    try {
      for (const entry of entries) {
        if (!mounted.current || current.current !== scope) break
        if (scope.cancelled.has(entry.id)) continue
        const controller = new AbortController()
        scope.controllers.set(entry.id, controller)
        patch(scope, entry.id, { status: 'uploading', message: '正在上传文件' })
        try {
          const document = await endpoints.uploadDocument(entry.kbId, scope.files.get(entry.id), { signal: controller.signal, requestId: entry.requestId })
          submitted(scope, entry, document)
        } catch (error) {
          await confirm(scope, entry, error)
        } finally { scope.controllers.delete(entry.id) }
      }
    } finally {
      scope.locked = false
      if (mounted.current && current.current === scope) setUploading(false)
    }
  }
  async function upload(selected, kbId) {
    const scope = current.current
    if (!kbId || !scope || scope.locked) return
    const signatures = new Set()
    const entries = Array.from(selected || []).filter(file => {
      const signature = `${file.name}:${file.size}:${file.lastModified}`
      if (signatures.has(signature)) return false
      signatures.add(signature)
      return true
    }).map(file => {
      const id = crypto.randomUUID()
      const entry = { id, requestId: id, kbId, name: file.name, status: 'pending', message: '等待上传' }
      scope.files.set(id, file)
      return entry
    })
    update(scope, items => [...items.slice(-40), ...entries])
    await submit(scope, entries)
  }
  async function cancel(entry) {
    const scope = current.current
    const item = scope.queue.find(item => item.id === entry.id)
    if (!item || !['pending', 'uploading', 'uncertain'].includes(item.status)) return
    scope.cancelled.add(item.id)
    if (item.status === 'pending') {
      scope.files.delete(item.id)
      patch(scope, item.id, { status: 'cancelled', message: '已取消等待上传' })
    } else {
      patch(scope, item.id, { status: 'cancelling', message: '正在确认服务端上传状态' })
      const controller = scope.controllers.get(item.id)
      if (controller) controller.abort()
      else await confirm(scope, item)
    }
  }
  async function retry(entry) {
    const scope = current.current
    if (scope.locked || entry.status !== 'failed') return
    if (!scope.files.has(entry.id)) { patch(scope, entry.id, { message: '文件已不在内存中，请重新选择文件' }); return }
    const next = { ...entry, requestId: crypto.randomUUID() }
    patch(scope, entry.id, { requestId: next.requestId })
    await submit(scope, [next])
  }
  return { queue, uploading, upload, cancel, retry }
}
