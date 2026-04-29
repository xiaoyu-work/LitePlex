import React, { memo, useMemo, useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import dynamic from 'next/dynamic'

// Dynamically import StockChart to avoid SSR issues
const StockChart = dynamic(
  () => import('./StockChart').then(mod => mod.StockChart),
  { 
    ssr: false,
    loading: () => <div className="h-[500px] bg-muted rounded-lg animate-pulse" />
  }
)

interface MemoizedMarkdownProps {
  content: string
  className?: string
}

// Split content into blocks for efficient rendering
function splitIntoBlocks(content: string): string[] {
  // Split by double newlines to create blocks
  const blocks = content.split(/\n\n/)
  return blocks
}

function toSuperscript(value: string): string {
  const chars: Record<string, string> = {
    '0': '⁰',
    '1': '¹',
    '2': '²',
    '3': '³',
    '4': '⁴',
    '5': '⁵',
    '6': '⁶',
    '7': '⁷',
    '8': '⁸',
    '9': '⁹',
    ',': ',',
    ' ': ' ',
    '-': '⁻'
  }

  return value.split('').map((char) => chars[char] ?? char).join('')
}

function expandCitationNumbers(value: string): number[] {
  const citations = new Set<number>()
  const parts = value.split(/[,;\s]+/).filter(Boolean)

  for (const part of parts) {
    if (part.includes('-')) {
      const [start, end] = part.split('-', 2).map(Number)
      if (Number.isInteger(start) && Number.isInteger(end) && start > 0 && end >= start && end <= 100) {
        for (let citation = start; citation <= end; citation += 1) {
          citations.add(citation)
        }
      }
      continue
    }

    const citation = Number(part)
    if (Number.isInteger(citation) && citation > 0) {
      citations.add(citation)
    }
  }

  return [...citations]
}

function normalizeMarkdown(content: string): string {
  return content.replace(/<sup>([\d,\s;-]+)<\/sup>/gi, (_, citation: string) => {
    const citationNumbers = expandCitationNumbers(citation)

    if (citationNumbers.length === 0) {
      return toSuperscript(citation)
    }

    return citationNumbers
      .map((citationNumber) => `[${toSuperscript(String(citationNumber))}](#source-${citationNumber})`)
      .join('')
  })
}

// Memoized block component
const MarkdownBlock = memo(({ block }: { block: string }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      components={{
        // Custom link component to open in new tab
        a: ({node: _node, href, className, ...props}) => {
          if (href?.startsWith('#source-')) {
            return (
              <a
                {...props}
                href={href}
                className={`align-super text-xs font-semibold text-blue-500 hover:text-blue-400 no-underline ml-0.5 ${className || ''}`}
              />
            )
          }

          return <a {...props} href={href} className={className} target="_blank" rel="noopener noreferrer" />
        },
        // Ensure proper heading sizes
        h1: ({node: _node, ...props}) => <h1 className="text-2xl font-bold my-4" {...props} />,
        h2: ({node: _node, ...props}) => <h2 className="text-xl font-semibold my-3" {...props} />,
        h3: ({node: _node, ...props}) => <h3 className="text-lg font-semibold my-2" {...props} />,
        // Style sup tags for citations
        sup: ({node: _node, ...props}) => <sup className="text-xs text-blue-500 hover:text-blue-400 cursor-pointer ml-0.5" {...props} />,
        // Properly format lists
        ul: ({node: _node, ...props}) => <ul className="list-disc list-inside my-2 space-y-1" {...props} />,
        ol: ({node: _node, ...props}) => <ol className="list-decimal list-inside my-2 space-y-1" {...props} />,
        li: ({node: _node, ...props}) => <li className="ml-4" {...props} />,
        // Code blocks
        code: ({node: _node, className, ...props}) => 
          !className ? (
            <code className="bg-gray-800 px-1.5 py-0.5 rounded text-sm" {...props} />
          ) : (
            <code className={`${className} block bg-gray-800 rounded-lg p-4 overflow-x-auto my-4`} {...props} />
          ),
        // Paragraphs
        p: ({node: _node, ...props}) => <p className="my-2 leading-relaxed" {...props} />,
      }}
    >
      {block}
    </ReactMarkdown>
  )
}, (prevProps, nextProps) => {
  // Only re-render if the block content actually changed
  return prevProps.block === nextProps.block
})

MarkdownBlock.displayName = 'MarkdownBlock'

// Main component with memoization
export const MemoizedMarkdown: React.FC<MemoizedMarkdownProps> = memo(({ content, className }) => {
  const [mounted, setMounted] = useState(false)
  
  useEffect(() => {
    setMounted(true)
  }, [])

  const normalizedContent = useMemo(() => normalizeMarkdown(content), [content])
  const blocks = useMemo(() => splitIntoBlocks(normalizedContent), [normalizedContent])
  
  // Check if content contains stock chart directive
  const stockChartMatch = content.match(/\[STOCK_CHART:([A-Z]+)\]/)
  
  if (stockChartMatch) {
    const symbol = stockChartMatch[1]
    // Replace the stock chart directive with the actual component
    const beforeChart = content.substring(0, stockChartMatch.index)
    const afterChart = content.substring((stockChartMatch.index || 0) + stockChartMatch[0].length)
    
    // During SSR, just show a placeholder
    if (!mounted) {
      return (
        <div className={className}>
          <div className="h-[500px] bg-muted rounded-lg animate-pulse" />
        </div>
      )
    }
    
    return (
      <div className={className}>
        {beforeChart && beforeChart.trim() && (
          <div className="mb-4">
            <MemoizedMarkdown content={beforeChart} />
          </div>
        )}
        <div className="my-4">
          <StockChart symbol={symbol} />
        </div>
        {afterChart && afterChart.trim() && (
          <div className="mt-4">
            <MemoizedMarkdown content={afterChart} />
          </div>
        )}
      </div>
    )
  }
  
  // For streaming, we want to handle incomplete markdown gracefully
  // If the last block is incomplete (e.g., in the middle of a list), 
  // we'll render it as-is and let ReactMarkdown handle it
  
  return (
    <div className={className}>
      {blocks.map((block, index) => {
        // Add a key that's stable for completed blocks
        // For the last block (which might be streaming), use content-based key
        const isLastBlock = index === blocks.length - 1
        const key = isLastBlock ? `block-${index}-${block.length}` : `block-${index}`
        
        return (
          <div key={key}>
            <MarkdownBlock block={block} />
            {/* Add spacing between blocks */}
            {index < blocks.length - 1 && <div className="my-2" />}
          </div>
        )
      })}
    </div>
  )
})

MemoizedMarkdown.displayName = 'MemoizedMarkdown'
