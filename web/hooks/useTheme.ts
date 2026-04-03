'use client'

import { useState, useEffect, useCallback } from 'react'

type Theme = 'dark' | 'light'

const STORAGE_KEY = 'valinor-theme'
const DEFAULT_THEME: Theme = 'dark'

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(DEFAULT_THEME)

  // On mount: read from localStorage and apply
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
    const initial = stored === 'light' ? 'light' : 'dark'
    setTheme(initial)
    applyTheme(initial)
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      localStorage.setItem(STORAGE_KEY, next)
      applyTheme(next)
      return next
    })
  }, [])

  return { theme, toggleTheme } as const
}

function applyTheme(theme: Theme) {
  const el = document.documentElement
  el.setAttribute('data-theme', theme)
  // Smooth transition for theme switch
  el.style.transition = 'background-color 300ms ease, color 300ms ease'
}
