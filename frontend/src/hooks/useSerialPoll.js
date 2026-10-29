import { useCallback, useEffect, useRef } from 'react'

// Events coalesce into one follow-up; timers begin only after work completes.
export function useSerialPoll(action, { interval = 10000, enabled = true, scope = '' } = {}) {
  const actionRef = useRef(action)
  const refreshRef = useRef(() => {})
  useEffect(() => { actionRef.current = action }, [action])
  useEffect(() => {
    if (!enabled) return
    let active = true, running = false, queued = false, timer
    const controller = new AbortController()
    const current = () => active
    async function run() {
      if (!active) return
      clearTimeout(timer)
      if (running) { queued = true; return }
      running = true
      try { await actionRef.current({ signal: controller.signal, current }) }
      finally {
        running = false
        if (active) {
          if (queued) { queued = false; void run() }
          else timer = setTimeout(run, interval)
        }
      }
    }
    refreshRef.current = run
    void run()
    return () => { active = false; controller.abort(); clearTimeout(timer); refreshRef.current = () => {} }
  }, [enabled, interval, scope])
  return useCallback(() => refreshRef.current(), [])
}
