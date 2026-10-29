import { useCallback, useEffect, useRef, useState } from 'react'

export default function useChatScroll(containerRef, messages) {
  const following = useRef(true)
  const [unseen, setUnseen] = useState(false)
  const scrollToBottom = useCallback(() => {
    following.current = true
    setUnseen(false)
    const node = containerRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [containerRef])
  useEffect(() => {
    const node = containerRef.current
    if (!node) return
    const onScroll = () => {
      following.current = node.scrollHeight - node.clientHeight - node.scrollTop <= 120
      if (following.current) setUnseen(false)
    }
    node.addEventListener('scroll', onScroll, { passive: true })
    return () => node.removeEventListener('scroll', onScroll)
  }, [containerRef])
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (following.current) scrollToBottom()
      else setUnseen(true)
    })
    return () => cancelAnimationFrame(frame)
  }, [messages, scrollToBottom])
  return { unseen, scrollToBottom }
}
