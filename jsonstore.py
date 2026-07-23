"""
Primitives de stockage JSON partagees.

Verrou global (le serveur tourne en mode threade) et ecritures atomiques
(fichier temporaire + rename) pour ne jamais laisser un JSON a moitie ecrit.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import secrets
import json
import os

import config

_LOCK = threading.RLock()


def now() -> float:
    import time
    return time.time()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def ensure_dirs() -> None:
    for d in (config.DATA_DIR, config.CONV_DIR, config.INDEX_DIR,
              config.ACTIONS_DIR, config.MEMORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data) -> None:
    """Ecriture atomique : on ecrit a cote puis on remplace."""
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def init() -> None:
    """A appeler une fois au demarrage."""
    ensure_dirs()
    if not config.INDEX_FILE.exists():
        write_json(config.INDEX_FILE, {"conversations": []})
    if not config.GLOBAL_MEMORY_FILE.exists():
        write_json(config.GLOBAL_MEMORY_FILE, {"facts": []})


def secret_key() -> str:
    """Cle de signature des cookies, persistante entre redemarrages."""
    with _LOCK:
        ensure_dirs()
        if config.SECRET_FILE.exists():
            return config.SECRET_FILE.read_text(encoding="utf-8").strip()
        key = secrets.token_hex(32)
        config.SECRET_FILE.write_text(key, encoding="utf-8")
        try:
            os.chmod(config.SECRET_FILE, 0o600)
        except OSError:
            pass
        return key
