export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
  thinking?: string
  status?: 'searching' | 'summarizing'
}

export interface StreamResponse {
  type: 'status' | 'thinking' | 'content' | 'done'
  status?: 'searching' | 'summarizing'
  content?: string
}