'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { ChevronLeft, Save, Info, Check } from 'lucide-react'
import {
  defaultSettings,
  getActiveLLMConfig,
  LLMProvider,
  LLMSettings,
  providerInfo,
  sanitizeSettings
} from '@/lib/llm-settings'

function loadInitialSettings(): LLMSettings {
  if (typeof window === 'undefined') {
    return defaultSettings
  }

  const savedSettings = localStorage.getItem('llmSettings')
  if (savedSettings) {
    try {
      return sanitizeSettings(JSON.parse(savedSettings))
    } catch (error) {
      console.error('Failed to parse settings:', error)
      return defaultSettings
    }
  }

  const legacyConfig = localStorage.getItem('llmConfig')
  if (legacyConfig) {
    try {
      const parsed = JSON.parse(legacyConfig) as { provider?: LLMProvider; modelName?: string; vllmUrl?: string }
      const provider = parsed.provider && parsed.provider in providerInfo ? parsed.provider : 'vllm'

      return sanitizeSettings({
        ...defaultSettings,
        activeProvider: provider,
        providers: {
          ...defaultSettings.providers,
          [provider]: parsed
        }
      })
    } catch (error) {
      console.error('Failed to parse legacy settings:', error)
    }
  }

  return defaultSettings
}

export default function SettingsPage() {
  const router = useRouter()
  const [initialSettings] = useState(loadInitialSettings)
  const [settings, setSettings] = useState<LLMSettings>(initialSettings)
  const [editingProvider, setEditingProvider] = useState<LLMProvider>(initialSettings.activeProvider)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    localStorage.setItem('llmSettings', JSON.stringify(settings))
    localStorage.setItem('llmConfig', JSON.stringify(getActiveLLMConfig(settings)))
  }, [settings])

  const handleProviderSelect = (provider: LLMProvider) => {
    setEditingProvider(provider)
  }

  const handleSetActive = (provider: LLMProvider) => {
    const newSettings = {
      ...settings,
      activeProvider: provider
    }
    setSettings(newSettings)
    
    // Immediately save to localStorage when setting active
    localStorage.setItem('llmSettings', JSON.stringify(newSettings))
    
    localStorage.setItem('llmConfig', JSON.stringify(getActiveLLMConfig(newSettings)))
    
    setMessage(`${providerInfo[provider].name} set as active provider`)
    setTimeout(() => setMessage(''), 2000)
  }

  const handleConfigChange = (field: string, value: string) => {
    setSettings(prev => ({
      ...prev,
      providers: {
        ...prev.providers,
        [editingProvider]: {
          ...prev.providers[editingProvider],
          [field]: value
        }
      }
    }))
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage('')

    try {
      // Save complete settings to localStorage
      localStorage.setItem('llmSettings', JSON.stringify(settings))
      
      const currentConfig = getActiveLLMConfig(settings)
      localStorage.setItem('llmConfig', JSON.stringify(currentConfig))
      
      // Try to send to backend
      try {
        const response = await fetch('/api/config', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(currentConfig)
        })

        if (response.ok) {
          setMessage('Settings saved successfully!')
        } else {
          setMessage('Settings saved locally')
        }
      } catch {
        setMessage('Settings saved locally')
      }
      
      setTimeout(() => setMessage(''), 3000)
    } catch {
      setMessage('Error saving settings')
      setTimeout(() => setMessage(''), 3000)
    } finally {
      setSaving(false)
    }
  }

  const currentProvider = providerInfo[editingProvider]
  const currentConfig = settings.providers[editingProvider] || {}
  const isConfigured = (provider: LLMProvider) => {
    const config = settings.providers[provider]
    const info = providerInfo[provider]
    
    if (info.fields.includes('vllmUrl') && !config?.vllmUrl) {
      return false
    }
    if (info.fields.includes('modelName') && !config?.modelName) {
      return false
    }
    return true
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b border-border">
        <div className="flex h-14 items-center px-4">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
          >
            <ChevronLeft className="h-5 w-5" />
            <span className="text-sm">Back</span>
          </button>
          <div className="flex-1 text-center">
            <h1 className="text-lg font-light">LLM Settings</h1>
          </div>
          <div className="w-20"></div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-5xl mx-auto p-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Provider List */}
          <div className="lg:col-span-1">
            <h2 className="text-lg font-light mb-4">Providers</h2>
            <div className="space-y-2">
              {Object.entries(providerInfo).map(([key, info]) => {
                const provider = key as LLMProvider
                const isActive = settings?.activeProvider === provider
                const isSelected = editingProvider === provider
                const configured = isConfigured(provider)
                
                return (
                  <button
                    key={key}
                    onClick={() => handleProviderSelect(provider)}
                    className={`w-full p-3 rounded-lg border text-left transition-all ${
                      isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-muted-foreground hover:bg-muted/30'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="font-medium flex items-center gap-2">
                          {info.name}
                          {isActive && (
                            <span className="text-xs bg-primary text-primary-foreground px-2 py-0.5 rounded">
                              Active
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          {configured ? '✓ Configured' : '○ Not configured'}
                        </div>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Configuration Form */}
          <div className="lg:col-span-2">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-light">Configure {currentProvider.name}</h2>
              {editingProvider !== settings.activeProvider && isConfigured(editingProvider) && (
                <button
                  onClick={() => handleSetActive(editingProvider)}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                >
                  <Check className="h-4 w-4" />
                  Set as Active
                </button>
              )}
            </div>

            <div className="space-y-6 bg-card p-6 rounded-lg border border-border">
              <p className="text-sm text-muted-foreground">{currentProvider.description}</p>

              {/* vLLM URL Field */}
              {currentProvider.fields.includes('vllmUrl') && (
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Server URL
                  </label>
                  <input
                    type="text"
                    value={currentConfig?.vllmUrl || ''}
                    onChange={(e) => handleConfigChange('vllmUrl', e.target.value)}
                    className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                    placeholder="http://localhost:1234/v1"
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    URL of your vLLM-compatible server endpoint (e.g., vLLM, Ollama, LM Studio)
                  </p>
                </div>
              )}

              {/* Model Name Field */}
              {currentProvider.fields.includes('modelName') && (
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Model Name
                  </label>
                  <input
                    type="text"
                    value={currentConfig?.modelName || ''}
                    onChange={(e) => handleConfigChange('modelName', e.target.value)}
                    className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                    placeholder={currentProvider.placeholder || currentProvider.defaults.modelName}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    {editingProvider === 'vllm' 
                      ? 'Path to your local model or model identifier'
                      : `Enter the ${currentProvider.name} model name you want to use`}
                  </p>
                </div>
              )}

              {/* Info Box */}
              <div className="flex items-start gap-3 p-4 bg-muted/30 rounded-lg">
                <Info className="h-5 w-5 text-muted-foreground mt-0.5" />
                <div className="text-sm text-muted-foreground">
                  {editingProvider === 'vllm' ? (
                    <div>
                      <p>Compatible with various local LLM servers:</p>
                      <ul className="mt-2 space-y-1 text-xs">
                        <li>• <strong>vLLM:</strong> Run with <code className="bg-background px-1 rounded">./start_vllm.sh</code></li>
                        <li>• <strong>Ollama:</strong> Use <code className="bg-background px-1 rounded">http://localhost:11434/v1</code></li>
                        <li>• <strong>LM Studio:</strong> Use <code className="bg-background px-1 rounded">http://localhost:1234/v1</code></li>
                        <li>• <strong>llama.cpp:</strong> Use server endpoint</li>
                      </ul>
                    </div>
                  ) : (
                    <p>
                      Set {currentProvider.envVar} in the backend environment. Browser storage is only used for
                      non-secret provider and model preferences.
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Save Button */}
            <div className="flex items-center justify-between pt-6">
              <div>
                {message && (
                  <p className={`text-sm ${message.includes('Error') ? 'text-red-500' : 'text-green-500'}`}>
                    {message}
                  </p>
                )}
              </div>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                <Save className="h-4 w-4" />
                {saving ? 'Saving...' : 'Save Settings'}
              </button>
            </div>
          </div>
        </div>

        {/* Active Provider Status */}
        <div className="mt-8 p-4 bg-muted/30 rounded-lg">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Currently Active Provider</p>
              <p className="text-lg">{providerInfo[settings.activeProvider].name}</p>
            </div>
            {!isConfigured(settings.activeProvider) && (
              <p className="text-sm text-orange-500">
                ⚠ Active provider is not fully configured
              </p>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
