import { NextRequest } from 'next/server'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const messages = Array.isArray(body.messages) ? body.messages : []
    const llmConfig = body.llmConfig || null
    const searchConfig = body.searchConfig || null
    
    // Check if messages exist and have content
    if (messages.length === 0) {
      return Response.json({ error: 'No messages provided' }, { status: 400 })
    }
    
    // Get the last message (the user's new message)
    const lastMessage = messages[messages.length - 1]
    const userMessage = lastMessage?.content || ''
    
    if (!userMessage) {
      return Response.json({ error: 'No message content provided' }, { status: 400 })
    }
    
    const sessionId = body.sessionId || crypto.randomUUID()
    const messageId = crypto.randomUUID()
    const textId = crypto.randomUUID()
    
    // Call your Python backend
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8088'
    const response = await fetch(`${backendUrl}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        messages: messages,
        chatId: body.chatId || 'default',
        sessionId: sessionId,
        llmConfig: llmConfig,
        searchConfig: searchConfig
      }),
    })
    
    if (!response.ok) {
      return Response.json(
        { error: `Backend error: ${response.status}` },
        { status: response.status }
      )
    }
    
    // Create a stream that follows AI SDK protocol
    const stream = new ReadableStream({
      async start(controller) {
        const reader = response.body?.getReader()
        const decoder = new TextDecoder()
        const encoder = new TextEncoder()
        
        if (!reader) {
          controller.error(new Error('Backend response body missing'))
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
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'status',
                      status: data.status
                    })}\n\n`))
                  } else if (data.type === 'thinking') {
                    // Send thinking content
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'thinking',
                      content: data.content
                    })}\n\n`))
                  } else if (data.type === 'content') {
                    // Send content as text delta
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'text-delta',
                      id: textId,
                      delta: data.content
                    })}\n\n`))
                  } else if (data.type === 'sources') {
                    // Send sources
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'sources',
                      sources: data.sources
                    })}\n\n`))
                  } else if (data.type === 'error') {
                    controller.enqueue(encoder.encode(`data: ${JSON.stringify({
                      type: 'error',
                      error: data.error || 'Generation failed'
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
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({
            type: 'error',
            error: 'Stream reading error'
          })}\n\n`))
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
    return Response.json({ error: 'Failed to process chat request' }, { status: 500 })
  }
}
