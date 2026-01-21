import { NextRequest } from 'next/server'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const messages = body.messages || []
    const llmConfig = body.llmConfig || null
    console.log('Received messages:', messages)
    console.log('Received LLM config:', llmConfig)
    
    // Check if messages exist and have content
    if (!messages || messages.length === 0) {
      throw new Error('No messages provided')
    }
    
    // Get the last message (the user's new message)
    const lastMessage = messages[messages.length - 1]
    const userMessage = lastMessage?.content || ''
    console.log('User message:', userMessage)
    
    if (!userMessage) {
      throw new Error('No message content provided')
    }
    
    // Create a unique session ID for this request
    const sessionId = Math.random().toString(36).substring(7)
    const messageId = Math.random().toString(36).substring(7)
    const textId = Math.random().toString(36).substring(7)
    
    // Call your Python backend
    const response = await fetch('http://localhost:8088/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        messages: messages,
        chatId: 'default',
        sessionId: sessionId,
        llmConfig: llmConfig
      }),
    })
    
    if (!response.ok) {
      throw new Error(`Backend error: ${response.status}`)
    }
    
    // Create a stream that follows AI SDK protocol
    const stream = new ReadableStream({
      async start(controller) {
        const reader = response.body?.getReader()
        const decoder = new TextDecoder()
        const encoder = new TextEncoder()
        
        if (!reader) {
          controller.close()
          return
        }
        
        // Send message start event
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({
          type: 'start',
          messageId: messageId
        })}\n\n`))
        
        // Send text part start
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({
          type: 'text-start',
          id: textId
        })}\n\n`))
        
        let buffer = ''
        let isThinking = false
        
        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            
            // Decode chunk and add to buffer
            buffer += decoder.decode(value, { stream: true })
            
            // Process complete lines
            const lines = buffer.split('\n')
            buffer = lines.pop() || '' // Keep incomplete line in buffer
            
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6))
                  
                  if (data.type === 'status') {
                    // Send status update
                    console.log('Backend status:', data.status)
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'status',
                      status: data.status
                    })}\n\n`))
                  } else if (data.type === 'thinking') {
                    // Send thinking content
                    console.log('Backend thinking:', data.content?.substring(0, 50))
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'thinking',
                      content: data.content
                    })}\n\n`))
                  } else if (data.type === 'content') {
                    // Send content as text delta
                    console.log('Sending content delta:', data.content)
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'text-delta',
                      id: textId,
                      delta: data.content
                    })}\n\n`))
                  } else if (data.type === 'sources') {
                    // Send sources
                    console.log('Backend sources:', data.sources?.length)
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'sources',
                      sources: data.sources
                    })}\n\n`))
                  }
                } catch (e) {
                  console.error('Error parsing SSE data:', e)
                }
              }
            }
          }
          
          // Send text part end
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({
            type: 'text-end',
            id: textId
          })}\n\n`))
          
          // Send stream end
          controller.enqueue(encoder.encode('data: [DONE]\n\n'))
          
        } catch (error) {
          console.error('Stream reading error:', error)
        } finally {
          controller.close()
        }
      },
    })
    
    // Return with proper headers for SSE
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'x-vercel-ai-ui-message-stream': 'v1'
      },
    })
    
  } catch (error) {
    console.error('API route error:', error)
    return new Response(
      JSON.stringify({ error: 'Failed to process chat request' }),
      { 
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      }
    )
  }
}