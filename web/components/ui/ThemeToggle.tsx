'use client'

import { useState } from 'react'
import { Sun, Moon } from 'lucide-react'
import { motion } from 'framer-motion'
import { useTheme } from '@/hooks/useTheme'
import { T } from '@/components/d4c/tokens'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const [hovered, setHovered] = useState(false)
  const isDark = theme === 'dark'

  return (
    <button
      onClick={toggleTheme}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={isDark ? 'Modo claro' : 'Modo oscuro'}
      aria-label={isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
      style={{
        width: 32,
        height: 32,
        borderRadius: '50%',
        border: T.border.subtle,
        backgroundColor: hovered ? T.bg.hover : T.bg.elevated,
        color: isDark ? T.accent.yellow : T.accent.blue,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 0,
        transition: 'background-color 150ms ease, color 150ms ease',
        flexShrink: 0,
      }}
    >
      <motion.div
        key={theme}
        initial={{ rotate: -90, opacity: 0 }}
        animate={{ rotate: 0, opacity: 1 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        {isDark ? <Sun size={16} /> : <Moon size={16} />}
      </motion.div>
    </button>
  )
}
