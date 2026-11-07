"""Minimal Ollama HTTP client built on the Python standard library."""

import json
import re
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from ..constants import SUPPORTED_MODELS

DEFAULT_BASE_URL = "http://localhost:11434"
MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}\Z")


class OllamaError(Exception):
    """A user-facing Ollama failure."""


def normalize_base_url(base_url):
    return (base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL


def valid_model_name(model):
    return isinstance(model, str) and MODEL_NAME_PATTERN.fullmatch(model.strip()) is not None


def model_options(base_url, current_model=None, timeout=1.5, installed_models=None):
    """Return built-in options plus all models installed in local Ollama."""
    if installed_models is None:
        try:
            installed = list_models(base_url, timeout=timeout)
        except OllamaError:
            installed = []
    else:
        installed = installed_models

    choices = []
    known = set()
    for model in SUPPORTED_MODELS:
        choices.append({**model, "installed": model["id"] in installed})
        known.add(model["id"])

    for name in installed:
        if name in known or not valid_model_name(name):
            continue
        choices.append({
            "id": name,
            "label": name,
            "note": "Locally installed",
            "installed": True,
        })
        known.add(name)

    if current_model and valid_model_name(current_model) and current_model not in known:
        choices.append({
            "id": current_model,
            "label": current_model,
            "note": "Not currently installed",
            "installed": False,
        })
    return choices


def _friendly_error(message, model=None):
    text = (message or "").strip()
    lowered = text.lower()
    if "not found" in lowered and "model" in lowered and model:
        return f"{text} Pull it first with: ollama pull {model}"
    if "connection refused" in lowered or "failed to connect" in lowered:
        return "Cannot reach Ollama. Start it with: ollama serve"
    return text or "Ollama returned an unknown error."


def list_models(base_url, timeout=4):
    """Return the names of locally installed Ollama models."""
    url = f"{normalize_base_url(base_url)}/api/tags"
    request = urlrequest.Request(url, headers={"Accept": "application/json"})
    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = [model.get("name", "") for model in payload.get("models", []) if model.get("name")]
        return list(dict.fromkeys(names))
    except HTTPError as error:
        raise OllamaError(f"Ollama responded with HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise OllamaError(
            f"Cannot reach Ollama at {normalize_base_url(base_url)}. "
            "Start it with: ollama serve"
        ) from error
    except ValueError as error:
        raise OllamaError("Ollama returned an invalid response.") from error


def status(base_url):
    """Return a serializable connection status object."""
    base = normalize_base_url(base_url)
    try:
        models = list_models(base)
        return {
            "available": True,
            "url": base,
            "models": models,
            "error": None,
        }
    except OllamaError as error:
        return {
            "available": False,
            "url": base,
            "models": [],
            "error": str(error),
        }


def stream_chat(base_url, model, messages, temperature=0.7, timeout=300):
    """Yield text chunks from Ollama's streaming chat endpoint."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature},
    }
    request = urlrequest.Request(
        f"{normalize_base_url(base_url)}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("error"):
                    raise OllamaError(_friendly_error(str(event["error"]), model))
                content = (event.get("message") or {}).get("content", "")
                if content:
                    yield content
                if event.get("done"):
                    break
    except HTTPError as error:
        detail = ""
        try:
            body = error.read().decode("utf-8", "replace")
            detail = json.loads(body).get("error", "")
        except (ValueError, OSError):
            detail = ""
        raise OllamaError(_friendly_error(detail or f"Ollama HTTP {error.code}.", model)) from error
    except OllamaError:
        raise
    except (URLError, TimeoutError, OSError) as error:
        raise OllamaError(
            f"Cannot reach Ollama at {normalize_base_url(base_url)}. "
            "Make sure it is running (ollama serve)."
        ) from error
