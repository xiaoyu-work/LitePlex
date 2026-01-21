'use client'

import { useEffect, useRef, useState } from 'react'
import Navbar from './Navbar'
import ChatInput from './ChatInput'
import { CollapsibleSources } from './CollapsibleSources'
import { MemoizedMarkdown } from './MemoizedMarkdown'
import { FormEvent } from 'react'

interface ChatInterfaceProps {
  chatId: string
  initialQuery?: string
}

interface Source {
  index: number
  title: string
  url: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  sources?: Source[]
  timestamp: Date
}

type WorkflowStatus = 'thinking' | 'searching' | 'summarizing' | null

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
  const [hasInitialized, setHasInitialized] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  

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

  // Handle initial query - auto-submit if coming from landing page
  useEffect(() => {
    console.log('Initial query effect:', { 
      initialQuery, 
      hasInitialized, 
      referrer: document.referrer,
      chatId 
    })
    
    if (initialQuery && !hasInitialized) {
      setHasInitialized(true)
      setInput(initialQuery)
      
      // Check if we already submitted this query
      const alreadySubmitted = sessionStorage.getItem(`chat-submitted-${chatId}`)
      console.log('Already submitted?', alreadySubmitted)
      
      if (!alreadySubmitted) {
        // Mark as submitted and auto-submit
        sessionStorage.setItem(`chat-submitted-${chatId}`, 'true')
        
        // Auto-submit immediately
        console.log('Auto-submitting query:', initialQuery)
        sendMessage(initialQuery)
      } else {
        console.log('Not auto-submitting (already submitted or refresh)')
      }
    }
  }, [initialQuery])

  const sendMessage = async (messageText: string) => {
    console.log('sendMessage called with:', messageText, 'isLoading:', isLoading)
    
    if (!messageText.trim() || isLoading) {
      console.log('sendMessage blocked - empty text or loading')
      return
    }
    
    // Create abort controller for this request
    abortControllerRef.current = new AbortController()
    
    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      timestamp: new Date()
    }
    
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setCurrentStatus('thinking')
    
    // Add assistant message placeholder
    const assistantMessageId = (Date.now() + 1).toString()
    const assistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      thinking: '',
      timestamp: new Date()
    }
    
    setMessages(prev => [...prev, assistantMessage])
    
    // Get LLM configuration from localStorage
    const llmConfig = localStorage.getItem('llmConfig')
    const config = llmConfig ? JSON.parse(llmConfig) : null
    
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
          llmConfig: config
        }),
        signal: abortControllerRef.current.signal
      })
      
      if (!response.ok) throw new Error('Failed to send message')
      
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      
      if (!reader) throw new Error('No reader available')
      
      let buffer = ''
      
      while (true) {
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
              console.log('Stream completed')
              break
            }
            
            try {
              const parsed = JSON.parse(data)
              // Log important events
              if (parsed.type === 'sources' || parsed.type === 'done') {
                console.log(`Event type: ${parsed.type}`, parsed)
              }
              
              // Handle different event types
              if (parsed.type === 'content' || parsed.type === 'text-delta') {
                setMessages(prev => {
                  const newMessages = [...prev]
                  const lastMessage = newMessages[newMessages.length - 1]
                  if (lastMessage.role === 'assistant') {
                    lastMessage.content += parsed.content || parsed.delta || ''
                  }
                  return newMessages
                })
              } else if (parsed.type === 'sources') {
                // Handle sources sent at the end
                console.log('Received sources:', parsed.sources)
                console.log('Sources count:', parsed.sources?.length)
                setMessages(prev => {
                  const newMessages = [...prev]
                  const lastMessage = newMessages[newMessages.length - 1]
                  if (lastMessage.role === 'assistant') {
                    // Create a new message object to trigger re-render
                    const updatedMessage = {
                      ...lastMessage,
                      sources: parsed.sources
                    }
                    newMessages[newMessages.length - 1] = updatedMessage
                    console.log('Updated message with sources:', updatedMessage)
                    console.log('Sources in updated message:', updatedMessage.sources)
                    // Force a re-render by returning a completely new array
                    return [...newMessages]
                  }
                  return prev
                })
              } else if (parsed.type === 'thinking') {
                // Handle thinking content
                setMessages(prev => {
                  const newMessages = [...prev]
                  const lastMessage = newMessages[newMessages.length - 1]
                  if (lastMessage.role === 'assistant') {
                    lastMessage.thinking = (lastMessage.thinking || '') + (parsed.content || '')
                  }
                  return newMessages
                })
              } else if (parsed.type === 'status') {
                // Update status
                if (parsed.status === 'searching') {
                  setCurrentStatus('searching')
                } else if (parsed.status === 'summarizing') {
                  setCurrentStatus('summarizing')
                }
              }
            } catch (e) {
              // Not JSON, might be raw text
              console.log('Raw data:', data)
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('Request aborted')
      } else {
        console.error('Error:', error)
        setMessages(prev => {
          const newMessages = [...prev]
          const lastMessage = newMessages[newMessages.length - 1]
          if (lastMessage.role === 'assistant') {
            lastMessage.content = 'Sorry, an error occurred. Please try again.'
          }
          return newMessages
        })
      }
    } finally {
      setIsLoading(false)
      setCurrentStatus(null)
      abortControllerRef.current = null
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  const stopGeneration = () => {
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
      searching: {
        text: 'Searching the web',
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
                      <>
                        {console.log('Rendering CollapsibleSources with:', message.sources)}
                        <CollapsibleSources sources={message.sources} />
                      </>
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