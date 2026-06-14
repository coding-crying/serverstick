#!/usr/bin/env bash
# ServerStick — Hardware scan for local LLM fit
# Called by Hermes via /skill llmfit-scan
# Outputs JSON for the Svelte GUI tier picker

set -euo pipefail

# ─── CPU detection ─────────────────────────────────────────────────
CPU_MODEL=$(lscpu 2>/dev/null | awk -F: '/Model name/{print $2; exit}' | xargs)
CPU_CORES=$(nproc 2>/dev/null || echo 1)
CPU_FLAGS=$(grep -m1 '^flags' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs)

# Determine x86 level (v1 = baseline SSE2, v2 = SSE4.2, v3 = AVX2, v4 = AVX-512)
CPU_LEVEL="x86_v1"
[[ "$CPU_FLAGS" == *"sse4_2"* ]] && CPU_LEVEL="x86_v2"
[[ "$CPU_FLAGS" == *"avx2"* ]] && CPU_LEVEL="x86_v3"
[[ "$CPU_FLAGS" == *"avx512f"* ]] && CPU_LEVEL="x86_v4"

# ─── Memory ────────────────────────────────────────────────────────
RAM_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")
[[ -z "$RAM_GB" || "$RAM_GB" -eq 0 ]] && RAM_GB=$(awk '/MemTotal/{printf "%.0f", $2/1024/1024}' /proc/meminfo 2>/dev/null)

# ─── Disk ──────────────────────────────────────────────────────────
DISK_GB=$(df -BG / 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G' || echo "0")

# ─── GPU detection ─────────────────────────────────────────────────
GPU_NAME="none"
GPU_VRAM_MB=0
if command -v nvidia-smi &>/dev/null; then
  GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | xargs)
  GPU_VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)
fi
[[ -z "$GPU_VRAM_MB" ]] && GPU_VRAM_MB=0

# ─── Tier determination ────────────────────────────────────────────
if [[ "$GPU_VRAM_MB" -ge 20000 ]]; then
  TIER="beast"
  MODEL="Qwen2.5-72B-Instruct"
  QUANT="Q4_K_M"
  SIZE_GB=42
  EXPECTED_TPS=18
  FALLBACK='[{"model":"Llama-3.1-70B-Instruct","quant":"Q4_K_M","size":40,"tps":15},{"model":"Qwen2.5-32B-Instruct","quant":"Q5_K_M","size":24,"tps":25}]'
elif [[ "$GPU_VRAM_MB" -ge 12000 ]]; then
  TIER="large"
  MODEL="Llama-3.1-8B-Instruct"
  QUANT="Q8_0"
  SIZE_GB=8.5
  EXPECTED_TPS=35
  FALLBACK='[{"model":"Mistral-7B-Instruct-v0.3","quant":"Q5_K_M","size":5.1,"tps":40},{"model":"Qwen2.5-14B-Instruct","quant":"Q4_K_M","size":9,"tps":22}]'
elif [[ "$RAM_GB" -ge 32 ]]; then
  TIER="medium-gpu-less"
  MODEL="Mistral-7B-Instruct-v0.3"
  QUANT="Q5_K_M"
  SIZE_GB=5.1
  EXPECTED_TPS=12
  FALLBACK='[{"model":"Llama-3.1-8B-Instruct","quant":"Q4_K_M","size":4.7,"tps":10},{"model":"Qwen2.5-7B-Instruct","quant":"Q5_K_M","size":5.4,"tps":11}]'
elif [[ "$RAM_GB" -ge 16 ]]; then
  TIER="medium"
  MODEL="Mistral-7B-Instruct-v0.3"
  QUANT="Q4_K_M"
  SIZE_GB=4.4
  EXPECTED_TPS=10
  FALLBACK='[{"model":"Llama-3.2-3B-Instruct","quant":"Q5_K_M","size":2.4,"tps":25},{"model":"Phi-3-medium-14B","quant":"Q3_K_M","size":8,"tps":6}]'
elif [[ "$RAM_GB" -ge 8 ]]; then
  TIER="small"
  MODEL="Llama-3.2-3B-Instruct"
  QUANT="Q5_K_M"
  SIZE_GB=2.4
  EXPECTED_TPS=18
  FALLBACK='[{"model":"Phi-3-mini-4K-Instruct","quant":"Q4_K_M","size":2.3,"tps":20},{"model":"Qwen2.5-1.5B-Instruct","quant":"Q8_0","size":1.9,"tps":40}]'
else
  TIER="tiny"
  MODEL="Llama-3.2-1B-Instruct"
  QUANT="Q8_0"
  SIZE_GB=1.3
  EXPECTED_TPS=30
  FALLBACK='[{"model":"Phi-3-mini-4K-Instruct","quant":"Q3_K_S","size":1.7,"tps":15}]'
fi

# ─── Output JSON ───────────────────────────────────────────────────
cat <<EOF
{
  "hardware": {
    "cpu": "$CPU_MODEL",
    "cpu_cores": $CPU_CORES,
    "cpu_level": "$CPU_LEVEL",
    "ram_gb": $RAM_GB,
    "disk_free_gb": $DISK_GB,
    "gpu": "$GPU_NAME",
    "gpu_vram_mb": $GPU_VRAM_MB
  },
  "tier": "$TIER",
  "recommended": {
    "model": "$MODEL",
    "quantization": "$QUANT",
    "size_gb": $SIZE_GB,
    "expected_tokens_per_sec": $EXPECTED_TPS,
    "huggingface_url": "https://huggingface.co/bartowski/${MODEL%-Instruct}-GGUF"
  },
  "fallback": $FALLBACK,
  "summary": "Tier $TIER on $CPU_LEVEL / ${RAM_GB}GB RAM / ${GPU_VRAM_MB}MB GPU VRAM — best fit: $MODEL ($QUANT, ~${EXPECTED_TPS} t/s)"
}
EOF
