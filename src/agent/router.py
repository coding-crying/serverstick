"""LLM Model Router — two-tier routing between DeepSeek V4 Flash and GLM 5.1.

Principle: Never silently downgrade. When in doubt, use the reasoning model.
"""

import os
import httpx
import json

# TokenRouter API config
TOKENROUTER_BASE = os.environ.get("TOKENROUTER_BASE", "https://api.tokenrouter.ai/v1")
TOKENROUTER_KEY = os.environ.get("TOKENROUTER_KEY", "")

# Model IDs
FLASH_MODEL = "deepseek-chat"       # DeepSeek V4 Flash — cheap, fast
REASONING_MODEL = "glm-5.1"         # GLM 5.1 — powerful, expensive

# Patterns that indicate simple service management — use flash model
SERVICE_MGMT_PATTERNS = [
    "start", "stop", "restart", "status", "install",
    "health", "logs", "update", "backup", "check",
    "list", "show", "get", "is ", "are ",
]

# Patterns that indicate complex reasoning — always use GLM
REASONING_PATTERNS = [
    "troubleshoot", "debug", "why", "error", "fail",
    "security", "vulnerability", "fix", "broken",
    "explain", "how does", "what if", "recommend",
]


def route_model(prompt: str, context: str = "") -> str:
    """Return the model ID to use based on task complexity.
    
    Args:
        prompt: The user/task prompt
        context: "user_chat" (always GLM), "service_mgmt" (flash), 
                 "diagnostics" (GLM), "" (auto-detect)
    
    Returns:
        Model ID string for TokenRouter
    """
    # Explicit user chat → always best model
    if context == "user_chat":
        return REASONING_MODEL
    
    # Explicit diagnostics → reasoning model
    if context == "diagnostics":
        return REASONING_MODEL
    
    # Explicit service management → cheap model
    if context == "service_mgmt":
        return FLASH_MODEL
    
    # Auto-detect from prompt content
    prompt_lower = prompt.lower()
    
    # Check for reasoning patterns first (higher priority)
    if any(p in prompt_lower for p in REASONING_PATTERNS):
        return REASONING_MODEL
    
    # Check for simple management patterns
    if any(p in prompt_lower for p in SERVICE_MGMT_PATTERNS):
        return FLASH_MODEL
    
    # Default to reasoning model — never silently downgrade
    return REASONING_MODEL


async def call_llm(model: str, prompt: str, system: str = "You are a helpful self-hosting assistant running on a ServerStick device. Be concise and practical.") -> str:
    """Call the LLM via TokenRouter API.
    
    Args:
        model: Model ID (deepseek-chat or glm-5.1)
        prompt: User message
        system: System prompt
    
    Returns:
        Assistant response text
    """
    if not TOKENROUTER_KEY:
        # Try SOPS-encrypted key
        try:
            import subprocess
            result = subprocess.run(
                ["sops", "-d", "--extract", '["TOKENROUTER_KEY"]', 
                 "/etc/serverstick/secrets/keys.yaml"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                api_key = result.stdout.strip().strip('"')
            else:
                return "Error: No API key configured. Set TOKENROUTER_KEY or configure SOPS."
        except Exception:
            return "Error: No API key configured."
    else:
        api_key = TOKENROUTER_KEY

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.post(
                f"{TOKENROUTER_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            return f"Error: LLM API returned {e.response.status_code}: {e.response.text[:200]}"
        except httpx.RequestError as e:
            return f"Error: Could not reach LLM API: {e}"


def get_model_info() -> dict:
    """Return info about available models for the dashboard."""
    return {
        "models": {
            FLASH_MODEL: {
                "name": "DeepSeek V4 Flash",
                "tier": "flash",
                "description": "Fast and cheap — service management, status checks",
            },
            REASONING_MODEL: {
                "name": "GLM 5.1",
                "tier": "reasoning",
                "description": "Powerful — troubleshooting, security, complex reasoning",
            },
        },
        "routing_rules": {
            "user_chat": REASONING_MODEL,
            "service_mgmt": FLASH_MODEL,
            "diagnostics": REASONING_MODEL,
            "auto": "pattern-matched",
        },
    }