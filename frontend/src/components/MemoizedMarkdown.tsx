import React, { memo, useMemo, useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import rehypeRaw from 'rehype-raw'
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

// Memoized block component
const MarkdownBlock = memo(({ block }: { block: string }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      rehypePlugins={[rehypeRaw]}
      components={{
        // Custom link component to open in new tab
        a: ({node, ...props}) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        // Ensure proper heading sizes
        h1: ({node, ...props}) => <h1 className="text-2xl font-bold my-4" {...props} />,
        h2: ({node, ...props}) => <h2 className="text-xl font-semibold my-3" {...props} />,
        h3: ({node, ...props}) => <h3 className="text-lg font-semibold my-2" {...props} />,
        // Style sup tags for citations
        sup: ({node, ...props}) => <sup className="text-xs text-blue-500 hover:text-blue-400 cursor-pointer ml-0.5" {...props} />,
        // Properly format lists
        ul: ({node, ...props}) => <ul className="list-disc list-inside my-2 space-y-1" {...props} />,
        ol: ({node, ...props}) => <ol className="list-decimal list-inside my-2 space-y-1" {...props} />,
        li: ({node, ...props}) => <li className="ml-4" {...props} />,
        // Code blocks
        code: ({node, inline, ...props}) => 
          inline ? (
            <code className="bg-gray-800 px-1.5 py-0.5 rounded text-sm" {...props} />
          ) : (
            <code className="block bg-gray-800 rounded-lg p-4 overflow-x-auto my-4" {...props} />
          ),
        // Paragraphs
        p: ({node, ...props}) => <p className="my-2 leading-relaxed" {...props} />,
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
  
  // Split content into blocks for efficient rendering
  const blocks = useMemo(() => splitIntoBlocks(content), [content])
  
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