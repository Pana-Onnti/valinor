'use client'

import { useState, useEffect, useRef } from 'react'

/**
 * Animates a number from 0 to target using requestAnimationFrame + ease-out cubic.
 * Returns the current animated value.
 */
export function useCountUp(target: number, duration = 800, delay = 0): number {
  const [value, setValue] = useState(0)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (target === 0) {
      setValue(0)
      return
    }

    let timeout: ReturnType<typeof setTimeout> | null = null

    const start = () => {
      const startTime = performance.now()

      const animate = (now: number) => {
        const elapsed = now - startTime
        const progress = Math.min(elapsed / duration, 1)
        // ease-out cubic
        const eased = 1 - Math.pow(1 - progress, 3)
        setValue(Math.round(eased * target))

        if (progress < 1) {
          rafRef.current = requestAnimationFrame(animate)
        }
      }

      rafRef.current = requestAnimationFrame(animate)
    }

    if (delay > 0) {
      timeout = setTimeout(start, delay)
    } else {
      start()
    }

    return () => {
      if (timeout) clearTimeout(timeout)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [target, duration, delay])

  return value
}
