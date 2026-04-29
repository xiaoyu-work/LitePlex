export interface SourceEvidence {
  text: string
  score?: number
}

export interface CitationCheck {
  cited: boolean
  confidence: 'supported' | 'partial' | 'low' | 'uncited'
  reason: string
  claims?: string[]
  matchedExcerpt?: string
  overlapTerms?: string[]
  checkedClaim?: string
}

export interface Source {
  index: number
  title: string
  url: string
  evidence?: SourceEvidence[]
  citationCheck?: CitationCheck
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
  thinking?: string
  status?: 'planning' | 'searching' | 'reading' | 'summarizing'
  sources?: Source[]
}

export interface StreamResponse {
  type: 'status' | 'thinking' | 'step' | 'content' | 'text-delta' | 'sources' | 'error' | 'done'
  status?: 'planning' | 'searching' | 'reading' | 'summarizing'
  content?: string
  delta?: string
  sources?: Source[]
  step?: unknown
  error?: string
}
