'use client'

import { useEffect, useRef, useState } from 'react'

interface StockChartProps {
  symbol: string
  theme?: 'light' | 'dark'
}

export function StockChart({ symbol, theme = 'light' }: StockChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)
  const [timeRange, setTimeRange] = useState<'1D' | '1W' | '1M' | '3M' | '1Y' | 'ALL'>('1M')
  const [interval, setInterval] = useState<'1m' | '5m' | '15m' | '1h' | '4h' | '1d'>('1h')
  const [showIntervalDropdown, setShowIntervalDropdown] = useState(false)

  useEffect(() => {
    let isSubscribed = true
    
    const initChart = async () => {
      if (!chartContainerRef.current || !isSubscribed) return

      try {
        // Import the library with all series types
        const LightweightCharts = await import('lightweight-charts')
        
        if (!isSubscribed || !chartContainerRef.current) return
        
        // Remove old chart if exists
        if (chartRef.current) {
          chartRef.current.remove()
          chartRef.current = null
        }
        
        // Create new chart with better interactivity
        const newChart = LightweightCharts.createChart(chartContainerRef.current, {
          layout: {
            background: { 
              type: LightweightCharts.ColorType.Solid, 
              color: theme === 'dark' ? '#1a1a1a' : '#ffffff' 
            },
            textColor: theme === 'dark' ? '#d1d5db' : '#333',
          },
          grid: {
            vertLines: { color: theme === 'dark' ? '#2a2a2a' : '#f0f0f0' },
            horzLines: { color: theme === 'dark' ? '#2a2a2a' : '#f0f0f0' },
          },
          width: chartContainerRef.current.clientWidth,
          height: 400,
          timeScale: {
            borderColor: theme === 'dark' ? '#2a2a2a' : '#f0f0f0',
            rightOffset: 5,
            barSpacing: 10,
            fixLeftEdge: false,
            fixRightEdge: false,
            visible: true,
            timeVisible: true,
            secondsVisible: false,
          },
          rightPriceScale: {
            borderColor: theme === 'dark' ? '#2a2a2a' : '#f0f0f0',
            autoScale: true,
          },
          handleScroll: {
            mouseWheel: true,
            pressedMouseMove: true,
            horzTouchDrag: true,
            vertTouchDrag: true,
          },
          handleScale: {
            axisPressedMouseMove: true,
            mouseWheel: true,
            pinch: true,
          },
        })
        
        chartRef.current = newChart

        // Create candlestick series using the new v5 API
        const candlestickSeries = newChart.addSeries(LightweightCharts.CandlestickSeries, {
          upColor: '#26a69a',
          downColor: '#ef5350',
          borderVisible: false,
          wickUpColor: '#26a69a',
          wickDownColor: '#ef5350',
        })

        // Generate candlestick data based on interval and timeRange
        const data = []
        const now = new Date()
        let currentPrice = 100 + Math.random() * 50
        
        // Calculate total milliseconds for time range
        let totalMs = 0
        switch (timeRange) {
          case '1D': totalMs = 24 * 60 * 60 * 1000; break
          case '1W': totalMs = 7 * 24 * 60 * 60 * 1000; break
          case '1M': totalMs = 30 * 24 * 60 * 60 * 1000; break
          case '3M': totalMs = 90 * 24 * 60 * 60 * 1000; break
          case '1Y': totalMs = 365 * 24 * 60 * 60 * 1000; break
          case 'ALL': totalMs = 730 * 24 * 60 * 60 * 1000; break
        }
        
        // Calculate interval in milliseconds
        let intervalMs = 0
        switch (interval) {
          case '1m': intervalMs = 60 * 1000; break
          case '5m': intervalMs = 5 * 60 * 1000; break
          case '15m': intervalMs = 15 * 60 * 1000; break
          case '1h': intervalMs = 60 * 60 * 1000; break
          case '4h': intervalMs = 4 * 60 * 60 * 1000; break
          case '1d': intervalMs = 24 * 60 * 60 * 1000; break
        }
        
        // Calculate number of candles
        const numCandles = Math.min(Math.floor(totalMs / intervalMs), 500) // Limit to 500 candles for performance
        
        for (let i = 0; i < numCandles; i++) {
          const timestamp = now.getTime() - (numCandles - i - 1) * intervalMs
          
          // Use timestamp for intraday, date string for daily
          const time = interval === '1d' 
            ? new Date(timestamp).toISOString().split('T')[0]
            : Math.floor(timestamp / 1000)
          
          // Generate realistic price movement
          const volatility = interval === '1m' ? 0.001 : 
                           interval === '5m' ? 0.002 : 
                           interval === '15m' ? 0.003 : 
                           interval === '1h' ? 0.005 : 
                           interval === '4h' ? 0.01 : 0.02
          
          const change = (Math.random() - 0.5) * currentPrice * volatility * 2
          const newPrice = currentPrice + change
          
          const open = currentPrice
          const close = newPrice
          const high = Math.max(open, close) + Math.abs(change * 0.3)
          const low = Math.min(open, close) - Math.abs(change * 0.3)
          
          data.push({
            time: time,
            open: Math.round(open * 100) / 100,
            high: Math.round(high * 100) / 100,
            low: Math.round(low * 100) / 100,
            close: Math.round(close * 100) / 100,
          })
          
          currentPrice = newPrice
        }
        
        candlestickSeries.setData(data)
        newChart.timeScale().fitContent()

        // Handle resize
        const handleResize = () => {
          if (chartContainerRef.current && chartRef.current) {
            chartRef.current.applyOptions({ 
              width: chartContainerRef.current.clientWidth 
            })
          }
        }

        window.addEventListener('resize', handleResize)
        
        return () => {
          window.removeEventListener('resize', handleResize)
        }
      } catch (error) {
        console.error('Failed to initialize chart:', error)
      }
    }

    initChart()

    return () => {
      isSubscribed = false
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [symbol, theme, timeRange, interval])

  return (
    <div className="w-full bg-card rounded-lg border border-border p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{symbol}</h2>
          <p className="text-sm text-muted-foreground">Stock Price Chart</p>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Interval Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowIntervalDropdown(!showIntervalDropdown)}
              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-muted rounded-lg hover:bg-muted/80 transition-colors"
            >
              <span className="text-muted-foreground">Interval:</span>
              <span className="text-foreground">{interval}</span>
              <svg
                className={`w-3 h-3 transition-transform ${showIntervalDropdown ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            
            {showIntervalDropdown && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setShowIntervalDropdown(false)}
                />
                <div className="absolute right-0 top-full mt-1 bg-popover border border-border rounded-lg shadow-lg z-20 py-1">
                  {(['1m', '5m', '15m', '1h', '4h', '1d'] as const).map((int) => (
                    <button
                      key={int}
                      onClick={() => {
                        setInterval(int)
                        setShowIntervalDropdown(false)
                      }}
                      className={`w-full px-4 py-1.5 text-xs text-left hover:bg-muted transition-colors ${
                        interval === int ? 'bg-muted text-foreground font-medium' : 'text-muted-foreground'
                      }`}
                    >
                      {int === '1m' && '1 minute'}
                      {int === '5m' && '5 minutes'}
                      {int === '15m' && '15 minutes'}
                      {int === '1h' && '1 hour'}
                      {int === '4h' && '4 hours'}
                      {int === '1d' && '1 day'}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          
          {/* Time Range Selector */}
          <div className="flex gap-1 bg-muted rounded-lg p-1">
            {(['1D', '1W', '1M', '3M', '1Y', 'ALL'] as const).map((range) => (
              <button
                key={range}
                onClick={() => setTimeRange(range)}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                  timeRange === range
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {range}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart Container */}
      <div ref={chartContainerRef} className="w-full h-[400px] bg-background" />

      {/* Additional Info */}
      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <span className="text-muted-foreground">Open: </span>
          <span className="font-medium">$150.25</span>
        </div>
        <div>
          <span className="text-muted-foreground">High: </span>
          <span className="font-medium">$152.30</span>
        </div>
        <div>
          <span className="text-muted-foreground">Low: </span>
          <span className="font-medium">$149.10</span>
        </div>
        <div>
          <span className="text-muted-foreground">Volume: </span>
          <span className="font-medium">45.2M</span>
        </div>
      </div>
    </div>
  )
}