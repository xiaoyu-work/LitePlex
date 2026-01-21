'use client'

import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { v4 as uuidv4 } from 'uuid'
import { ThemeToggle } from '@/components/ThemeToggle'
import { SettingsDropdown } from '@/components/SettingsDropdown'

export default function HomePage() {
  const [query, setQuery] = useState('')
  const router = useRouter()

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      const chatId = uuidv4()
      router.push(`/search/${chatId}?q=${encodeURIComponent(query)}`)
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 w-full bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex h-14 items-center px-4">
          <div className="flex flex-1 items-center">
            {/* Logo removed */}
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <SettingsDropdown />
          </div>
        </div>
      </nav>

      {/* Main content */}
      <div className="flex-1 flex items-center justify-center px-4 -mt-20">
        <div className="w-full max-w-2xl">
          {/* Logo above search box */}
          <div className="text-center mb-12">
            <h1 className="text-6xl font-light text-foreground tracking-tight">LitePlex</h1>
          </div>
          
          {/* Search input */}
          <form onSubmit={handleSubmit} className="relative">
            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full px-5 py-3 pr-12 text-base font-light border border-border rounded-full focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent bg-card text-card-foreground shadow-md hover:shadow-lg transition-shadow"
                placeholder="Ask anything..."
                autoFocus
              />
              <button
                type="submit"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-muted-foreground hover:text-foreground transition-colors hover:bg-muted rounded-full"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="11" cy="11" r="8"></circle>
                  <path d="m21 21-4.35-4.35"></path>
                </svg>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}