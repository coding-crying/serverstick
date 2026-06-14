---
name: llmfit-scan
description: Scan this device's hardware (CPU, RAM, disk, GPU) to determine which LLM models will fit at acceptable speed. Used during onboarding when user picks the "Local AI" tier.
version: 1.0.0
triggers:
  - "/llmfit"
  - "what model can I run"
  - "scan my hardware"
  - "local AI"
---

# LLM Fit Scanner

Determine which quantized LLM models will run well on this device.

## When to use
- Onboarding wizard step 3 ("Pick AI tier") → user picks "Local"
- User says "I want to run an LLM locally"

## What it does
1. Detect CPU: `lscpu`, `cat /proc/cpuinfo | grep flags | head -1`
2. Detect RAM: `free -g | awk '/Mem:/{print $2}'`
3. Detect disk free: `df -BG / | tail -1 | awk '{print $4}'`
4. Detect GPU: `lspci | grep -i nvidia` → `nvidia-smi --query-gpu=memory.total --format=csv,noheader`
5. Determine tier:
   - **Tiny** (<8GB RAM, no GPU): Phi-3-mini Q4 (~2.3GB), Llama-3.2-1B
   - **Small** (8-16GB RAM): Llama-3.2-3B Q4, Mistral-7B Q4_K_M
   - **Medium** (16-32GB RAM, no GPU): Mistral-7B Q5, Llama-3.1-8B Q4
   - **Large** (32GB+ RAM or 12GB+ GPU): Llama-3.1-8B Q8, Qwen2.5-14B
   - **Beast** (24GB GPU): Llama-3.1-70B Q4, Qwen-72B
6. Recommend model + quantization + expected tokens/sec
7. If `llmfit` CLI is installed, call it directly; otherwise use our heuristic

## Output format
```json
{
  "tier": "medium",
  "recommended": {
    "model": "Mistral-7B-Instruct-v0.3",
    "quantization": "Q4_K_M",
    "size_gb": 4.4,
    "expected_tps": 12
  },
  "fallback": [...]
}
```

## CLI
```bash
bash /etc/serverstick/scripts/llmfit-scan.sh
```
