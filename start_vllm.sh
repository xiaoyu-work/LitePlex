#!/bin/bash

# Start vLLM server with proper configuration for Jan-v1-4B model

# Default values
PORT=${1:-1234}
TP_SIZE=${2:-4}  # tensor-parallel-size
MODEL_PATH=${3:-"./Jan-v1-4B"}

# Show usage if help is requested
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    echo "Usage: $0 [PORT] [TP_SIZE] [MODEL_PATH]"
    echo ""
    echo "Arguments:"
    echo "  PORT        Port number for vLLM server (default: 1234)"
    echo "  TP_SIZE     Tensor parallel size / Number of GPUs (default: 4)"
    echo "  MODEL_PATH  Path to model (default: ./Jan-v1-4B)"
    echo ""
    echo "Examples:"
    echo "  $0                    # Use all defaults"
    echo "  $0 8080               # Use port 8080, other defaults"
    echo "  $0 8080 8             # Use port 8080, 8 GPUs"
    echo "  $0 8080 8 ./my-model # Custom port, GPUs, and model path"
    exit 0
fi

echo "Starting vLLM server..."
echo "  Port: $PORT"
echo "  Tensor Parallel Size: $TP_SIZE"
echo "  Model: $MODEL_PATH"
echo ""

# Activate conda environment
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate perp 2>/dev/null || {
        echo "Error: conda environment 'perp' not found"
        echo "Create it with: conda create -n perp python=3.10 -y"
        exit 1
    }
fi

# Kill any existing vLLM processes
pkill -f "vllm.entrypoints.openai.api_server" 2>/dev/null || true

# Start vLLM with parameters
vllm serve "$MODEL_PATH" \
    --port "$PORT" \
    --max-model-len 32768 \
    --tensor-parallel-size "$TP_SIZE" \
    --dtype float16 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes