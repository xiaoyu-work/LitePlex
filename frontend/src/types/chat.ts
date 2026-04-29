export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
  thinking?: string
  status?: 'planning' | 'searching' | 'reading' | 'summarizing'
}

export interface StreamResponse {
  type: 'status' | 'thinking' | 'step' | 'content' | 'done'
  status?: 'planning' | 'searching' | 'reading' | 'summarizing'
  content?: string
}
