import { useCallback, useEffect, useRef, useState } from 'react'

const identity = value => value
// Each region can finish or retry independently. Invalidating a read before a
// mutation prevents its old snapshot from overwriting the mutation receipt.
export default function useIndependentRead(read, valid, select = identity) {
  const [state, setState] = useState({ data: null, loading: true, error: false })
  const mounted = useRef(false)
  const generation = useRef(0)
  const flight = useRef(null)
  const invalidate = useCallback(() => {
    generation.current++
    flight.current?.controller.abort()
    flight.current = null
    if (mounted.current) setState(old => ({ ...old, loading: false }))
  }, [])
  const refresh = useCallback(() => {
    if (!mounted.current) return Promise.resolve()
    if (flight.current) return flight.current.promise
    const version = ++generation.current, controller = new AbortController()
    const request = { controller }
    flight.current = request
    setState(old => ({ ...old, loading: true }))
    request.promise = (async () => {
      try {
        const value = await read({ signal: controller.signal })
        if (!valid(value)) throw new Error('Invalid collection response')
        if (mounted.current && generation.current === version) setState({ data: select(value), loading: false, error: false })
      } catch {
        if (mounted.current && generation.current === version) setState(old => ({ ...old, loading: false, error: true }))
      } finally { if (flight.current === request) flight.current = null }
    })()
    return request.promise
  }, [read, valid, select])
  useEffect(() => {
    mounted.current = true
    void refresh()
    return () => { mounted.current = false; invalidate() }
  }, [refresh, invalidate])
  const commit = useCallback(update => {
    invalidate()
    if (mounted.current) setState(old => ({ ...old, data: update(old.data || []) }))
  }, [invalidate])
  return { ...state, refresh, invalidate, commit }
}

