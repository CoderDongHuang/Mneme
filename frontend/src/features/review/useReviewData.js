import { useCallback, useEffect, useRef, useState } from 'react'
import { endpoints } from '../../api/client'

// The two reads have independent lifetimes. Refreshing plans must not reset a
// flipped card, and an older card read must not overwrite a saved rating.
function useReviewList(read) {
  const generation = useRef(0)
  const alive = useRef(false)
  const [state, setState] = useState({ items: null, loading: true, error: '' })
  const refresh = useCallback(async () => {
    const request = ++generation.current
    setState(old => ({ ...old, loading: true, error: '' }))
    try {
      const items = await read()
      if (alive.current && request === generation.current) setState({ items, loading: false, error: '' })
    } catch (error) {
      if (alive.current && request === generation.current) setState(old => ({ ...old, loading: false, error: error.message }))
    }
  }, [read])
  useEffect(() => {
    alive.current = true
    void refresh()
    return () => { alive.current = false }
  }, [refresh])
  const replace = useCallback(saved => {
    generation.current++
    setState(old => ({ ...old, loading: false, items: (old.items || []).some(item => item.id === saved.id)
      ? old.items.map(item => item.id === saved.id ? saved : item) : [...(old.items || []), saved] }))
  }, [])
  return { ...state, refresh, replace }
}

export default function useReviewData() {
  const cards = useReviewList(endpoints.reviews)
  const plans = useReviewList(endpoints.plans)
  return { cards, plans }
}
