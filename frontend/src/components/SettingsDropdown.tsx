'use client'

import { Settings, Cpu, Info } from 'lucide-react'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

export function SettingsDropdown() {
  const [isOpen, setIsOpen] = useState(false)
  const router = useRouter()

  const openAbout = () => {
    window.open('https://github.com/xiaoyu-work/LitePlex', '_blank')
    setIsOpen(false)
  }

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground h-9 w-9"
        aria-label="Settings"
      >
        <Settings className="h-5 w-5" />
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute right-0 top-full mt-2 w-56 rounded-lg border border-border bg-popover p-1 shadow-lg z-50">
            <button
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors hover:bg-accent hover:text-accent-foreground"
              onClick={() => {
                router.push('/settings')
                setIsOpen(false)
              }}
            >
              <Cpu className="h-4 w-4" />
              <span>LLM Settings</span>
            </button>
            <button
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors hover:bg-accent hover:text-accent-foreground"
              onClick={openAbout}
            >
              <Info className="h-4 w-4" />
              <span>About / GitHub</span>
            </button>
          </div>
        </>
      )}
    </div>
  )
}