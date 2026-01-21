#!/bin/bash

echo "Starting Perplexity-style Assistant..."
echo "======================================="

# Activate conda environment and run the assistant
eval "$(conda shell.bash hook)"
conda activate perp
python perplexity.py