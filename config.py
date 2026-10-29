import json
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
PI_BIN = os.environ.get("PI_BIN", "/opt/homebrew/bin/pi")

# Mac mini d1 endpoint
D1_URL = os.environ.get("D1_URL", "http://100.126.106.26:8004/mcp")

# Qwen Server defaults (fallback to ~/.pi/agent/models.json if present)
DEFAULT_QWEN_BASE = "https://test.edmundhaacke.com/v1"
DEFAULT_QWEN_KEY = "cuT5coE2W9XweseEBlism7HL2tqRqw0iGeyFK3EvO1qKMIADX5D86Lt6woX1JDcLo"
DEFAULT_QWEN_MODEL = "unsloth-ud-iq4_xs"

def load_qwen_config() -> tuple[str, str, str]:
    """Reads Qwen config from env or ~/.pi/agent/models.json."""
    base_url = os.environ.get("QWEN_API_BASE", DEFAULT_QWEN_BASE)
    api_key = os.environ.get("QWEN_API_KEY", DEFAULT_QWEN_KEY)
    model = os.environ.get("QWEN_MODEL", DEFAULT_QWEN_MODEL)
    
    pi_models_file = Path.home() / ".pi" / "agent" / "models.json"
    if pi_models_file.exists():
        try:
            with open(pi_models_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                prov = data.get("providers", {}).get("local-llama", {})
                if prov.get("baseUrl"):
                    base_url = prov["baseUrl"]
                if prov.get("apiKey"):
                    api_key = prov["apiKey"]
                models = prov.get("models", [])
                if models and isinstance(models, list) and models[0].get("id"):
                    model = models[0]["id"]
        except Exception:
            pass

    return base_url, api_key, model
