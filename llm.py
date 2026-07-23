"""
Acces au modele Ollama et controle de sante.

Chaque appel peut cibler un modele different (un modele par role) ; les
reglages de ressources (contexte, threads) viennent de config.
"""

from __future__ import annotations

import json

import requests

import config
import websearch


def ollama_stream(system, prompt, temperature=0.6, max_tokens=1200, model=None):
    """Diffuse la reponse du modele token par token."""
    model = model or config.MODEL
    options = {"temperature": temperature, "top_p": 0.9,
               "num_predict": max_tokens, "num_ctx": config.NUM_CTX}
    if config.NUM_THREAD > 0:
        options["num_thread"] = config.NUM_THREAD
    try:
        r = requests.post(
            f"{config.OLLAMA_URL}/api/generate",
            json={"model": model, "system": system, "prompt": prompt,
                  "stream": True, "options": options},
            stream=True, timeout=600)
        if r.status_code != 200:
            yield f"[Ollama a repondu {r.status_code}. Verifie le modele '{model}' : ollama list]"
            return
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("response"):
                yield chunk["response"]
            if chunk.get("done"):
                break
    except requests.exceptions.ConnectionError:
        yield "[Ollama injoignable. Lance 'ollama serve' puis reessaie.]"
    except requests.exceptions.Timeout:
        yield "[Delai depasse. Le modele met trop de temps sur cette machine.]"
    except Exception as exc:  # noqa: BLE001
        yield f"[Erreur : {exc}]"


def complete(system, prompt, temperature=0.5, max_tokens=1000, model=None) -> str:
    """Version non diffusee, pour les etapes internes."""
    return "".join(ollama_stream(system, prompt, temperature, max_tokens, model))


def sse(event, **payload):
    return f"data: {json.dumps({'event': event, **payload}, ensure_ascii=False)}\n\n"


def _model_present(name, installed):
    """Ollama tolere l'absence de tag :latest — compare le nom nu aussi."""
    base = name.split(":")[0]
    return any(n == name or n.split(":")[0] == base for n in installed)


def health():
    r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
    names = [m["name"] for m in r.json().get("models", [])]
    roles = {role: {"model": m, "present": _model_present(m, names)}
             for role, m in config.ROLE_MODELS.items()}
    missing = sorted({info["model"] for info in roles.values() if not info["present"]})
    return {"status": "connected", "model": config.MODEL,
            "model_present": _model_present(config.MODEL, names),
            "roles": roles, "missing": missing,
            "available": names, "search": websearch.search_label()}
