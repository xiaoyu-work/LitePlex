'use client'

import { useParams, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'
import ChatInterface from '@/components/ChatInterface'

export default function SearchPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const chatId = params.id as string
  const initialQuery = searchParams.get('q') || ''

  return <ChatInterface chatId={chatId} initialQuery={initialQuery} />
}