import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/client'

export default function useUploadQueue(storageKey, onSubmitted) {
  const [queue, setQueue] = useState(() => {
    try {
      const items = JSON.parse(localStorage.getItem(storageKey) || '[]')
      return Array.isArray(items) ? items.slice(-40).map(item => ['pending', 'uploading'].includes(item.status)
        ? { ...item, status: 'cancelled', message: '页面已重新加载，请重新选择文件' } : item) : []
    } catch { return [] }
  })
  const [uploading, setUploading] = useState(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const locked = useRef(false)
  const files = useRef(new Map())
  const cancelled = useRef(new Set())
  function update(change) {
    setQueue(current => {
      const next = typeof change === 'function' ? change(current) : change
      try { localStorage.setItem(storageKey, JSON.stringify(next.slice(-40))) } catch { /* uploads also work without local storage */ }
      return next
    })
  }
  const patch = (id, values) => update(current => current.map(item => item.id === id ? { ...item, ...values } : item))
  async function submit(entries) {
    if (locked.current || !entries.length) return
    locked.current = true
    setUploading(true)
    try {
      for (const entry of entries) {
        if (!mounted.current) break
        if (cancelled.current.has(entry.id)) continue
        patch(entry.id, { status: 'uploading', message: '正在提交解析任务' })
        try {
          const document = await endpoints.uploadDocument(entry.kbId, files.current.get(entry.id))
          if (mounted.current) onSubmitted(entry.kbId, document)
          patch(entry.id, { status: 'submitted', message: '已提交，等待服务端解析', documentId: document.id })
          files.current.delete(entry.id)
        } catch (error) {
          patch(entry.id, { status: 'failed', message: error.message })
        }
      }
    } finally { locked.current = false; setUploading(false) }
  }
  async function upload(selected, kbId) {
    if (!kbId || locked.current) return
    const signatures = new Set()
    const entries = Array.from(selected || []).filter(file => {
      const signature = `${file.name}:${file.size}:${file.lastModified}`
      if (signatures.has(signature)) return false
      signatures.add(signature)
      return true
    }).map(file => {
      const entry = { id: crypto.randomUUID(), kbId, name: file.name, status: 'pending', message: '等待上传' }
      files.current.set(entry.id, file)
      return entry
    })
    update(current => [...current.slice(-40), ...entries])
    await submit(entries)
  }
  function cancel(entry) {
    if (entry.status !== 'pending') return
    cancelled.current.add(entry.id)
    files.current.delete(entry.id)
    patch(entry.id, { status: 'cancelled', message: '已取消上传' })
  }
  async function retry(entry) {
    if (!files.current.has(entry.id)) { patch(entry.id, { message: '文件已不在内存中，请重新选择文件' }); return }
    await submit([entry])
  }
  return { queue, uploading, upload, cancel, retry }
}
