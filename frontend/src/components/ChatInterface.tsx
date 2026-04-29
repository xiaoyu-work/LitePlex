'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Navbar from './Navbar'
import ChatInput from './ChatInput'
import { CollapsibleSources } from './CollapsibleSources'
import { MemoizedMarkdown } from './MemoizedMarkdown'
import { sanitizeActiveLLMConfig } from '@/lib/llm-settings'

interface ChatInterfaceProps {
  chatId: string
  initialQuery?: string
}

interface Source {
  index: number
  title: string
  url: string
}

type ResearchStepStatus = 'active' | 'done' | 'error'

interface ResearchStep {
  id: string
  label: string
  status: ResearchStepStatus
  detail?: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  sources?: Source[]
  steps?: ResearchStep[]
  timestamp: Date
}

type WorkflowStatus = 'thinking' | 'planning' | 'searching' | 'reading' | 'summarizing' | null

function createId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function readStoredLLMConfig() {
  const llmConfig = localStorage.getItem('llmConfig')
  if (!llmConfig) {
    return null
  }

  try {
    return sanitizeActiveLLMConfig(JSON.parse(llmConfig))
  } catch (error) {
    console.error('Failed to parse saved LLM config:', error)
    return null
  }
}

function normalizeStep(input: unknown): ResearchStep | null {
  if (!input || typeof input !== 'object') {
    return null
  }

  const step = input as Partial<ResearchStep>
  const validStatuses: ResearchStepStatus[] = ['active', 'done', 'error']

  if (
    typeof step.id !== 'string' ||
    typeof step.label !== 'string' ||
    !validStatuses.includes(step.status as ResearchStepStatus)
  ) {
    return null
  }

  return {
    id: step.id,
    label: step.label,
    status: step.status as ResearchStepStatus,
    detail: typeof step.detail === 'string' ? step.detail : undefined
  }
}

export default function ChatInterface({ chatId, initialQuery }: ChatInterfaceProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [messages, setMessages] = useState<Message[]>(() => {
    // Load messages from sessionStorage on mount
    if (typeof window !== 'undefined') {
      const saved = sessionStorage.getItem(`chat-messages-${chatId}`)
      if (saved) {
        try {
          return JSON.parse(saved)
        } catch (e) {
          console.error('Failed to parse saved messages:', e)
        }
      }
    }
    return []
  })
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [currentStatus, setCurrentStatus] = useState<WorkflowStatus>(null)
  const hasInitializedRef = useRef(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const activeSessionIdRef = useRef<string | null>(null)

  const updateLastAssistantMessage = useCallback((updater: (message: Message) => Message) => {
    setMessages(prev => {
      const lastIndex = prev.length - 1
      const lastMessage = prev[lastIndex]

      if (!lastMessage || lastMessage.role !== 'assistant') {
        return prev
      }

      return prev.map((message, index) => index === lastIndex ? updater(message) : message)
    })
  }, [])

  // Save messages to sessionStorage whenever they change
  useEffect(() => {
    if (messages.length > 0 && typeof window !== 'undefined') {
      sessionStorage.setItem(`chat-messages-${chatId}`, JSON.stringify(messages))
    }
  }, [messages, chatId])

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async (messageText: string) => {
    if (!messageText.trim() || isLoading) {
      return
    }
    
    // Create abort controller for this request
    abortControllerRef.current = new AbortController()
    const sessionId = createId()
    activeSessionIdRef.current = sessionId
    
    // Add user message
    const userMessage: Message = {
      id: createId(),
      role: 'user',
      content: messageText,
      timestamp: new Date()
    }
    
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setCurrentStatus('thinking')
    
    // Add assistant message placeholder
    const assistantMessage: Message = {
      id: createId(),
      role: 'assistant',
      content: '',
      thinking: '',
      timestamp: new Date()
    }
    
    setMessages(prev => [...prev, assistantMessage])
    
    const config = readStoredLLMConfig()
    
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: [...messages, userMessage].map(m => ({
            role: m.role,
            content: m.content
          })),
          chatId,
          sessionId,
          llmConfig: config
        }),
        signal: abortControllerRef.current.signal
      })
      
      if (!response.ok) throw new Error('Failed to send message')
      
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      
      if (!reader) throw new Error('No reader available')
      
      let buffer = ''
      let streamDone = false
      
      while (!streamDone) {
        const { done, value } = await reader.read()
        if (done) break
        
        // Decode the chunk
        const chunk = decoder.decode(value, { stream: true })
        buffer += chunk
        
        // Process complete lines
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            
            if (data === '[DONE]') {
              streamDone = true
              break
            }
            
            try {
              const parsed = JSON.parse(data)
               
              // Handle different event types
              if (parsed.type === 'content' || parsed.type === 'text-delta') {
                const delta = parsed.content || parsed.delta || ''
                updateLastAssistantMessage(message => ({
                  ...message,
                  content: message.content + delta
                }))
              } else if (parsed.type === 'sources') {
                // Handle sources sent at the end
                updateLastAssistantMessage(message => ({
                  ...message,
                  sources: parsed.sources
                }))
              } else if (parsed.type === 'thinking') {
                // Handle thinking content
                updateLastAssistantMessage(message => ({
                  ...message,
                  thinking: (message.thinking || '') + (parsed.content || '')
                }))
              } else if (parsed.type === 'step') {
                const step = normalizeStep(parsed.step)
                if (step) {
                  updateLastAssistantMessage(message => {
                    const steps = message.steps || []
                    const existingIndex = steps.findIndex(existingStep => existingStep.id === step.id)

                    if (existingIndex >= 0) {
                      return {
                        ...message,
                        steps: steps.map((existingStep, index) => index === existingIndex ? step : existingStep)
                      }
                    }

                    return {
                      ...message,
                      steps: [...steps, step]
                    }
                  })
                }
              } else if (parsed.type === 'status') {
                // Update status
                if (parsed.status === 'planning') {
                  setCurrentStatus('planning')
                } else if (parsed.status === 'searching') {
                  setCurrentStatus('searching')
                } else if (parsed.status === 'reading') {
                  setCurrentStatus('reading')
                } else if (parsed.status === 'summarizing') {
                  setCurrentStatus('summarizing')
                }
              } else if (parsed.type === 'error') {
                updateLastAssistantMessage(message => ({
                  ...message,
                  content: parsed.error || 'Sorry, an error occurred. Please try again.'
                }))
              }
            } catch (e) {
              console.error('Failed to parse stream data:', e)
            }
          }
        }
      }
    } catch (error) {
      const isAbortError = error instanceof DOMException && error.name === 'AbortError'
      if (!isAbortError) {
        console.error('Error:', error)
        updateLastAssistantMessage(message => ({
          ...message,
          content: 'Sorry, an error occurred. Please try again.'
        }))
      }
    } finally {
      setIsLoading(false)
      setCurrentStatus(null)
      abortControllerRef.current = null
      activeSessionIdRef.current = null
    }
  }, [chatId, isLoading, messages, updateLastAssistantMessage])

  // Handle initial query - auto-submit if coming from landing page
  useEffect(() => {
    if (initialQuery && !hasInitializedRef.current) {
      hasInitializedRef.current = true

      // Check if we already submitted this query
      const alreadySubmitted = sessionStorage.getItem(`chat-submitted-${chatId}`)
      
      if (!alreadySubmitted) {
        // Mark as submitted and auto-submit
        sessionStorage.setItem(`chat-submitted-${chatId}`, 'true')
        
        const timeoutId = window.setTimeout(() => {
          sendMessage(initialQuery)
        }, 0)

        return () => window.clearTimeout(timeoutId)
      }
    }
  }, [chatId, initialQuery, sendMessage])

  const handleSubmit = () => {
    sendMessage(input)
  }

  const stopGeneration = () => {
    const sessionId = activeSessionIdRef.current

    if (sessionId) {
      void fetch('/api/stop', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ sessionId }),
      }).catch((error) => {
        console.error('Failed to stop backend generation:', error)
      })
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
  }

  // Status indicator component
  const StatusIndicator = ({ status }: { status: WorkflowStatus }) => {
    if (!status) return null
    
    const statusConfig = {
      thinking: {
        text: 'Thinking',
        icon: '',
      },
      planning: {
        text: 'Planning research',
        icon: '',
      },
      searching: {
        text: 'Searching the web',
        icon: '',
      },
      reading: {
        text: 'Reading sources',
        icon: '',
      },
      summarizing: {
        text: 'Summarizing results',
        icon: '',
      }
    }
    
    const config = statusConfig[status]
    
    return (
      <div className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full border bg-muted/50 border-border">
        <span className="text-sm font-medium text-muted-foreground">
          {config.text}
        </span>
        <span className="inline-flex text-muted-foreground" style={{ width: '20px' }}>
          <span className="loading-dot-1">.</span>
          <span className="loading-dot-2">.</span>
          <span className="loading-dot-3">.</span>
        </span>
      </div>
    )
  }

  const AgentSteps = ({ steps }: { steps?: ResearchStep[] }) => {
    if (!steps || steps.length === 0) return null

    const statusClass: Record<ResearchStepStatus, string> = {
      active: 'border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-300',
      done: 'border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-300',
      error: 'border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-300',
    }

    const marker: Record<ResearchStepStatus, string> = {
      active: '…',
      done: '✓',
      error: '!',
    }

    return (
      <div className="mb-4 rounded-lg border border-border bg-muted/20 p-3">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
          Agent activity
        </div>
        <div className="space-y-2">
          {steps.map((step) => (
            <div
              key={step.id}
              className={`rounded-md border px-3 py-2 text-sm ${statusClass[step.status]}`}
            >
              <div className="flex items-center gap-2">
                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-background/70 text-xs">
                  {marker[step.status]}
                </span>
                <span className="font-medium">{step.label}</span>
              </div>
              {step.detail && (
                <div className="mt-1 pl-7 text-xs opacity-80">
                  {step.detail}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 py-6">
          {/* Display all messages in conversation order */}
          {messages.map((message, index) => (
            <div key={message.id} className="mb-8">
              {/* User Message */}
              {message.role === 'user' && (
                <div className="mb-6">
                  <h2 className="text-xl font-semibold text-foreground mb-2">
                    {index === 0 ? (
                      // First question - larger title
                      <span className="text-2xl">{message.content}</span>
                    ) : (
                      // Follow-up questions
                      <>
                        <span className="text-sm text-muted-foreground font-normal">Follow-up:</span>
                        <br />
                        <span className="text-lg">{message.content}</span>
                      </>
                    )}
                  </h2>
                </div>
              )}

              {/* Assistant Message */}
              {message.role === 'assistant' && (
                <>
                  {/* Show status indicator only for the current loading message */}
                  {isLoading && index === messages.length - 1 && currentStatus && (
                    <div className="mb-4">
                      <StatusIndicator status={currentStatus} />
                    </div>
                  )}

                  <AgentSteps steps={message.steps} />

                  {/* Reasoning Section (if exists) */}
                  {message.thinking && (
                    <details className="mb-4 group">
                      <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1">
                        <svg className="w-4 h-4 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                        Show reasoning
                      </summary>
                      <div className="mt-2 p-3 bg-muted/30 border border-border/50 rounded-lg text-sm text-muted-foreground whitespace-pre-wrap">
                        {message.thinking}
                      </div>
                    </details>
                  )}

                  {/* Assistant Response */}
                  {message.content && (
                    <>
                      <div className="prose prose-slate dark:prose-invert max-w-none animate-fade-in">
                        <MemoizedMarkdown 
                          content={message.content}
                          className="markdown-content"
                        />
                      </div>
                    
                    {/* Collapsible Sources - show when available */}
                    {message.sources && message.sources.length > 0 && (
                      <CollapsibleSources sources={message.sources} />
                    )}
                    </>
                  )}

                  {/* Add separator between Q&A pairs except for the last one */}
                  {index < messages.length - 1 && (
                    <div className="border-b border-border/30 my-8"></div>
                  )}
                </>
              )}
            </div>
          ))}
          
          <div ref={messagesEndRef} className="h-24" />
        </div>
      </div>

      <div className="sticky bottom-0 w-full bg-gradient-to-t from-background via-background to-transparent pt-4 pb-6">
        <div className="max-w-4xl mx-auto px-4">
          <ChatInput
            value={input}
            onChange={setInput}
            onSubmit={handleSubmit}
            onStop={stopGeneration}
            disabled={isLoading}
            isProcessing={isLoading}
          />
        </div>
      </div>
    </div>
  )
}
