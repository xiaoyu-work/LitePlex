'use client'

import { useRef, useEffect, FormEvent, KeyboardEvent } from 'react'

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (e: FormEvent) => void
  onStop?: () => void
  disabled?: boolean
  isProcessing?: boolean
}

export default function ChatInput({ value, onChange, onSubmit, onStop, disabled, isProcessing }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'
    }
  }, [value])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isProcessing) {
      e.preventDefault()
      onSubmit(e as any)
    }
  }

  return (
    <form onSubmit={onSubmit} className="relative">
      <div className="bg-popover border border-border rounded-2xl transition-colors focus-within:border-ring shadow-sm">
        <div className="flex items-end gap-2 p-2">
          <div className="flex-1">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full min-h-[56px] max-h-[200px] px-4 py-4 bg-transparent border-none outline-none resize-none text-foreground text-sm leading-relaxed placeholder:text-muted-foreground"
              placeholder={isProcessing ? "Generating response..." : "Ask anything..."}
              rows={1}
              autoComplete="off"
              disabled={disabled}
            />
          </div>
          <div className="flex items-center gap-2 mb-2">
            {isProcessing ? (
              <button
                type="button"
                onClick={onStop}
                className="p-2 bg-destructive text-destructive-foreground rounded-md transition-all hover:bg-destructive/90"
                title="Stop generation"
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
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                </svg>
              </button>
            ) : (
              <button
                type="submit"
                disabled={disabled || !value?.trim()}
                className="p-2 bg-primary text-primary-foreground rounded-md transition-all hover:bg-primary/90 disabled:opacity-30 disabled:cursor-not-allowed"
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
                  <line x1="12" y1="19" x2="12" y2="5"></line>
                  <polyline points="5 12 12 5 19 12"></polyline>
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>
    </form>
  )
}