#!/usr/bin/env python3
"""
Headless entry point for the C64 AI proxy server.

Reads provider, model, and API keys from environment variables and/or
c64_ai_proxy_config.json (same file the GUI writes), then runs the server
on port 6464 until SIGTERM/SIGINT.

Env vars (override any saved config):
  C64_PROVIDER      One of: Claude, Gemini, OpenAI, Ollama, LM Studio
  C64_MODEL         Model id for the active provider
  ANTHROPIC_API_KEY
  GEMINI_API_KEY
  OPENAI_API_KEY
  OLLAMA_URL        host:port or full URL (default localhost:11434)
  LMSTUDIO_URL      host:port or full URL (default localhost:1234)
"""

import os
import signal
import sys
import time

from c64_ai_proxy import PROVIDERS, ProxyServer, load_config


def build_api_keys(config):
    return {
        "Claude": os.environ.get("ANTHROPIC_API_KEY") or config.get("key_Claude", ""),
        "Gemini": os.environ.get("GEMINI_API_KEY") or config.get("key_Gemini", ""),
        "OpenAI": os.environ.get("OPENAI_API_KEY") or config.get("key_OpenAI", ""),
        "Ollama": os.environ.get("OLLAMA_URL") or config.get("key_Ollama", "localhost:11434"),
        "LM Studio": os.environ.get("LMSTUDIO_URL") or config.get("key_LM Studio", "localhost:1234"),
    }


def main():
    config = load_config()
    provider = os.environ.get("C64_PROVIDER") or config.get("provider", "Ollama")
    if provider not in PROVIDERS:
        print(f"ERROR: unknown C64_PROVIDER '{provider}'. Valid: {list(PROVIDERS)}", file=sys.stderr)
        sys.exit(2)
    model = os.environ.get("C64_MODEL") or config.get("model", "")
    api_keys = build_api_keys(config)
    active_key = api_keys.get(provider, "")

    if provider not in ("Ollama", "LM Studio") and not active_key:
        print(f"ERROR: {provider} requires an API key. Set the env var and restart.", file=sys.stderr)
        sys.exit(2)
    if not model:
        print("WARNING: C64_MODEL not set — client must pick one with /MODEL before chatting.", file=sys.stderr)

    server = ProxyServer(log_callback=None)
    server.provider_name = provider
    server.model = model
    server.api_key = active_key
    server.api_keys = api_keys

    print(f"Starting C64 AI proxy: provider={provider} model={model or '(unset)'}", flush=True)
    server.start()

    stop = {"flag": False}

    def _handle(signum, _frame):
        print(f"Received signal {signum}, stopping...", flush=True)
        stop["flag"] = True
        server.stop()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    while not stop["flag"] and server.running:
        time.sleep(1)


if __name__ == "__main__":
    main()
