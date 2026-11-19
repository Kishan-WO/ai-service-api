import { useEffect, useState } from 'react'

// 'system' follows the operating system; 'light' and 'dark' are set by the user and remembered.
const KEY = 'ai-service-theme'

function apply(mode) {
  const root = document.documentElement
  if (mode === 'light' || mode === 'dark') root.dataset.theme = mode
  else delete root.dataset.theme
}

export function useTheme() {
  const [mode, setMode] = useState(() => {
    try {
      return localStorage.getItem(KEY) || 'system'
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    apply(mode)
    try {
      localStorage.setItem(KEY, mode)
    } catch {
      /* private mode: the choice just is not remembered */
    }
  }, [mode])
  const next = { system: 'light', light: 'dark', dark: 'system' }
  return { mode, cycle: () => setMode(next[mode]) }
}
