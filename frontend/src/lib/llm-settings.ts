export type LLMProvider = 'vllm' | 'openai' | 'anthropic' | 'google' | 'deepseek' | 'qwen'

export interface ProviderConfig {
  modelName?: string
  vllmUrl?: string
}

export interface LLMSettings {
  activeProvider: LLMProvider
  providers: Record<LLMProvider, ProviderConfig>
}

export interface ActiveLLMConfig extends ProviderConfig {
  provider: LLMProvider
}

interface ProviderInfo {
  name: string
  description: string
  fields: Array<keyof ProviderConfig>
  defaults: ProviderConfig
  placeholder?: string
  envVar?: string
}

export const providerInfo: Record<LLMProvider, ProviderInfo> = {
  vllm: {
    name: 'Local/vLLM Server',
    description: 'Connect to a local or remote OpenAI-compatible inference server (vLLM, Ollama, LM Studio, etc.)',
    fields: ['vllmUrl', 'modelName'],
    defaults: {
      vllmUrl: 'http://localhost:1234/v1',
      modelName: './Jan-v1-4B'
    }
  },
  openai: {
    name: 'OpenAI',
    description: 'Use OpenAI GPT models. API keys are read from the backend environment.',
    fields: ['modelName'],
    defaults: {
      modelName: 'gpt-4-turbo-preview'
    },
    placeholder: 'e.g., gpt-4-turbo-preview, gpt-4, gpt-3.5-turbo',
    envVar: 'OPENAI_API_KEY'
  },
  anthropic: {
    name: 'Anthropic Claude',
    description: 'Use Anthropic Claude models. API keys are read from the backend environment.',
    fields: ['modelName'],
    defaults: {
      modelName: 'claude-3-opus-20240229'
    },
    placeholder: 'e.g., claude-3-opus-20240229, claude-3-sonnet-20240229',
    envVar: 'ANTHROPIC_API_KEY'
  },
  google: {
    name: 'Google Gemini',
    description: 'Use Google Gemini models. API keys are read from the backend environment.',
    fields: ['modelName'],
    defaults: {
      modelName: 'gemini-pro'
    },
    placeholder: 'e.g., gemini-pro, gemini-1.5-pro, gemini-pro-vision',
    envVar: 'GOOGLE_API_KEY'
  },
  deepseek: {
    name: 'DeepSeek',
    description: 'Use DeepSeek models. API keys are read from the backend environment.',
    fields: ['modelName'],
    defaults: {
      modelName: 'deepseek-chat'
    },
    placeholder: 'e.g., deepseek-chat, deepseek-coder',
    envVar: 'DEEPSEEK_API_KEY'
  },
  qwen: {
    name: 'Qwen (通义千问)',
    description: 'Use Alibaba Qwen models. API keys are read from the backend environment.',
    fields: ['modelName'],
    defaults: {
      modelName: 'qwen-turbo'
    },
    placeholder: 'e.g., qwen-turbo, qwen-plus, qwen-max',
    envVar: 'DASHSCOPE_API_KEY'
  }
}

export const providerKeys = Object.keys(providerInfo) as LLMProvider[]

export const defaultSettings: LLMSettings = {
  activeProvider: 'vllm',
  providers: {
    vllm: {
      vllmUrl: 'http://localhost:1234/v1',
      modelName: './Jan-v1-4B'
    },
    openai: { modelName: 'gpt-4-turbo-preview' },
    anthropic: { modelName: 'claude-3-opus-20240229' },
    google: { modelName: 'gemini-pro' },
    deepseek: { modelName: 'deepseek-chat' },
    qwen: { modelName: 'qwen-turbo' }
  }
}

function isProvider(value: unknown): value is LLMProvider {
  return typeof value === 'string' && providerKeys.includes(value as LLMProvider)
}

function readString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function sanitizeProviderConfig(provider: LLMProvider, input: unknown): ProviderConfig {
  const info = providerInfo[provider]
  const source = typeof input === 'object' && input !== null ? input as Record<string, unknown> : {}
  const config: ProviderConfig = { ...info.defaults }

  for (const field of info.fields) {
    const value = readString(source[field])
    if (value) {
      config[field] = value
    }
  }

  return config
}

export function sanitizeSettings(input: unknown): LLMSettings {
  const source = typeof input === 'object' && input !== null ? input as Record<string, unknown> : {}
  const providersSource = typeof source.providers === 'object' && source.providers !== null
    ? source.providers as Record<string, unknown>
    : {}

  const providers = providerKeys.reduce((acc, provider) => {
    acc[provider] = sanitizeProviderConfig(provider, providersSource[provider])
    return acc
  }, {} as Record<LLMProvider, ProviderConfig>)

  return {
    activeProvider: isProvider(source.activeProvider) ? source.activeProvider : defaultSettings.activeProvider,
    providers
  }
}

export function sanitizeActiveLLMConfig(input: unknown): ActiveLLMConfig | null {
  const source = typeof input === 'object' && input !== null ? input as Record<string, unknown> : {}
  if (!isProvider(source.provider)) {
    return null
  }

  return {
    provider: source.provider,
    ...sanitizeProviderConfig(source.provider, source)
  }
}

export function getActiveLLMConfig(settings: LLMSettings): ActiveLLMConfig {
  return {
    provider: settings.activeProvider,
    ...sanitizeProviderConfig(settings.activeProvider, settings.providers[settings.activeProvider])
  }
}

