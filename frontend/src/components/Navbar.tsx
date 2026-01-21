import Link from 'next/link'
import { ThemeToggle } from './ThemeToggle'
import { SettingsDropdown } from './SettingsDropdown'

export default function Navbar() {
  return (
    <nav className="sticky top-0 z-50 w-full bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center px-4">
        <div className="flex flex-1 items-center">
          <Link href="/" className="flex items-center space-x-2">
            <span className="font-light text-xl">LitePlex</span>
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <SettingsDropdown />
        </div>
      </div>
    </nav>
  )
}