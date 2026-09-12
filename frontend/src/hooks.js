import { useEffect, useState } from 'react'

export const MOBILE_QUERY = '(max-width: 767px)'

// true under 768 px (the phone layout); updates on resize / rotation
export function useMobile() {
  const get = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(MOBILE_QUERY).matches : false)
  const [mobile, setMobile] = useState(get)
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY)
    const h = () => setMobile(mq.matches)
    mq.addEventListener ? mq.addEventListener('change', h) : mq.addListener(h)
    return () => { mq.removeEventListener ? mq.removeEventListener('change', h) : mq.removeListener(h) }
  }, [])
  return mobile
}

// the height of the visible part of the page (shrinks when the on-screen keyboard opens)
export function useVisualViewportHeight() {
  const get = () => (typeof window !== 'undefined' ? Math.round(window.visualViewport?.height || window.innerHeight) : 0)
  const [h, setH] = useState(get)
  useEffect(() => {
    const vv = window.visualViewport
    const on = () => setH(get())
    if (vv) { vv.addEventListener('resize', on); vv.addEventListener('scroll', on) }
    window.addEventListener('resize', on)
    return () => { if (vv) { vv.removeEventListener('resize', on); vv.removeEventListener('scroll', on) } window.removeEventListener('resize', on) }
  }, [])
  return h
}
