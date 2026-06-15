# Self-hosted Infra for NemoClaw/Hermes

Anything that needs to be local to the sandbox (not downloaded at install time) lives here.

## Layout

```
self-hosted-infra/
  README.md                   — this file
  models/                     — bundled GGUF models (committed via git-lfs, not by default)
    tiny/
      Llama-3.2-1B-Instruct-Q8_0.gguf
    small/
      Llama-3.2-3B-Instruct-Q5_K_M.gguf
      Phi-3-mini-4K-Instruct-Q4_K_M.gguf
    medium/
      Mistral-7B-Instruct-v0.3-Q4_K_M.gguf
      Mistral-7B-Instruct-v0.3-Q5_K_M.gguf
  configs/                    — NemoClaw config templates
    inference.local.yaml      — local inference routing
    network-policy.yaml       — default policy: allow list
  bin/                        — bundled binaries
    llama-server              — fallback if system llama.cpp unavailable
```

## Inference routing

NemoClaw uses an `inference.local` proxy to route model traffic. Config:

```yaml
# configs/inference.local.yaml
routes:
  - match: { tier: local }
    target: http://host.containers.internal:8081  # llama.cpp server on host
  - match: { tier: byo, provider: openai }
    target: ${OPENAI_BASE_URL}
    auth: bearer
  - match: { tier: managed }
    target: https://api.tokenrouter.com/v1
    auth: bearer
```

The NemoClaw sandbox reaches the host's llama.cpp server via `host.containers.internal` (Docker Desktop) or the host's LAN IP in Linux bridge mode.

## Network policy

Default policy is permissive for known services, restrictive for everything else:

```yaml
# configs/network-policy.yaml
allow:
  - huggingface.co
  - pypi.org
  - files.pythonhosted.org
  - ghcr.io
  - registry-1.docker.io
  - api.openai.com
  - api.anthropic.com
  - api.groq.com
  - api.together.xyz
  - api.tokenrouter.com
  - pangolin.serverstick.com
  - get.serverstick.com
  - api.serverstick.com
deny:
  - '*'  # default deny
```

This is written to `/sandbox/.hermes/policy.yaml` by `apply-tier.sh`.

## Bundled binaries

If the host doesn't have `llama-server` in PATH, the bundle falls back to the binary in `bin/llama-server` (built from llama.cpp latest release). For hackathon demo, this is optional — most targets will have `llama.cpp` installable via `apt install llama.cpp` or similar.
