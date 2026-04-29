# LitePlex - Perplexity-style Search Assistant

A high-performance, Perplexity-style search assistant built with LangGraph and Next.js. Features real-time web search, streaming responses, and a modern UI.

## Features

- Real-time web search with Google Serper API
- Research agent flow with query planning, source-page reading, and evidence extraction
- Evidence-level source drill-down with lightweight citation confidence checks
- Streaming responses
- Multiple LLM providers support (OpenAI, Anthropic, Google, DeepSeek, Qwen, local vLLM)
- Modern Next.js frontend
- Provider/model selection via UI without storing API keys in the browser

## Prerequisites

- Python 3.10+
- Node.js 20.9+ (Node.js 24 is recommended for the current Next.js version)
- uv
- Google Serper API key
- At least one LLM API key (OpenAI, Anthropic, etc.) or local LLM setup

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/xiaoyu-work/LitePlex.git
cd LitePlex
```

### 2. Set up Python environment

```bash
uv run --python 3.10 --with-requirements requirements.txt python -c "import liteplex"
```

### 3. (Optional) Install vLLM for local LLM serving

```bash
# Linux/WSL only
uv pip install -r requirements-vllm.txt
```

### 4. Set up Frontend
```bash
cd frontend
npm ci
cd ..
```

### 5. Configure environment variables
```bash
cp .env.example .env
# Edit .env with your API keys
```

## LLM Backend Options

LitePlex supports multiple LLM backends. Choose one that suits your needs:

| Provider | API Key Env Variable | Notes |
|----------|---------------------|-------|
| OpenAI | `OPENAI_API_KEY` | GPT-4, GPT-3.5 |
| Anthropic | `ANTHROPIC_API_KEY` | Claude models |
| Google | `GOOGLE_API_KEY` | Gemini models |
| DeepSeek | `DEEPSEEK_API_KEY` | DeepSeek models |
| Alibaba Qwen | `DASHSCOPE_API_KEY` | Qwen models |
| Local Server | - | vLLM, Ollama, LM Studio, llama.cpp (any OpenAI-compatible API) |

API keys are read only from the backend environment. The Settings page stores non-secret provider, model, and local server URL preferences in browser storage.

## Usage

### Quick Start (All-in-One)
```bash
# Start everything with one command (Linux/Mac)
./start.sh
```
Then open http://localhost:3000 in your browser.

### Manual Start

#### 1. (Optional) Start vLLM Server
```bash
./start_vllm.sh [PORT] [TP_SIZE] [MODEL_PATH]

# Examples:
./start_vllm.sh                    # Default: port 1234, 4 GPUs
./start_vllm.sh 8080               # Custom port 8080
./start_vllm.sh 8080 8             # 8 GPUs
./start_vllm.sh 8080 8 ./my-model  # Custom model
```

#### 2. Start Backend API
```bash
uv run --python 3.10 --with-requirements requirements.txt python web_app.py
```
The API will run on http://localhost:8088 by default.

You can customize the host and port using environment variables:
```bash
BACKEND_HOST=127.0.0.1 BACKEND_PORT=8080 uv run --python 3.10 --with-requirements requirements.txt python web_app.py
```

#### 3. Start Frontend
```bash
cd frontend
npm run dev
```
The UI will be available at http://localhost:3000

### CLI Usage
For command-line interface:
```bash
uv run --python 3.10 --with-requirements requirements.txt python liteplex.py
```

## Configuration

### Environment Variables (.env)
```bash
# Google Serper API Configuration (required for web search)
SERPER_API_KEY=your-api-key-here

# LLM Provider API Keys (at least one required)
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
GOOGLE_API_KEY=your-google-key
DEEPSEEK_API_KEY=your-deepseek-key
DASHSCOPE_API_KEY=your-dashscope-key

# vLLM Server Configuration (optional, for local LLM)
VLLM_URL=http://localhost:1234/v1
MODEL_NAME=./Jan-v1-4B

# Backend Server Configuration (optional)
BACKEND_PORT=8088
BACKEND_HOST=0.0.0.0

# Source reader controls (optional)
SOURCE_READER_MAX_SOURCES=5
SOURCE_READER_MAX_CHARS=400000
SOURCE_READER_TIMEOUT_SECONDS=6
SOURCE_READER_FALLBACK_SOURCES=3
SOURCE_READER_CACHE_TTL_SECONDS=1800
SEARCH_CACHE_TTL_SECONDS=300

# Frontend Backend URL (optional, for deployment)
# Server-side URL used by the Next.js API route
# BACKEND_URL=http://localhost:8088

# Allowed browser origins for backend CORS (comma-separated)
# FRONTEND_ORIGINS=http://localhost:3000
```

Research acceleration uses short in-memory TTL caches for Serper results and fetched source-page text. Set `SEARCH_CACHE_TTL_SECONDS=0` or `SOURCE_READER_CACHE_TTL_SECONDS=0` to disable either cache; source evidence is still scored fresh for each question. `SOURCE_READER_FALLBACK_SOURCES` lets the reader try extra unique URLs when some pages are slow, unsupported, or low-signal.

## Quality checks

```bash
uv run --python 3.10 python -m py_compile web_app.py liteplex.py

cd frontend
npm ci
npm audit --audit-level=low
npm run lint
npm run type-check
npm run build
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
