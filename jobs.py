"""
Registre de taches en memoire, pour executer l'equipe d'agents en arriere-plan
et laisser le client recuperer les evenements par sondage (polling).

Pourquoi pas du SSE pur : sur un reseau mobile ou derriere certains proxys, une
connexion HTTP longue (plusieurs minutes, le temps que l'equipe travaille) est
souvent coupee cote reseau, meme avec un battement de cœur — ce n'est pas
toujours reparable cote serveur. De courtes requetes GET repetees traversent
ces reseaux sans probleme : c'est le meme principe que la reconnexion SSE, en
plus tolerant.

Chaque tache garde la liste ordonnee de ses evenements (deja formates en JSON
« sse-like ») ; le client demande « tout ce qui est apres l'index N ».
"""

from __future__ import annotations

import threading
import secrets
import time

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}

# Purge des taches trop vieilles pour ne pas accumuler en memoire indefiniment.
_MAX_AGE = 3600


def create_job() -> str:
    job_id = secrets.token_hex(8)
    with _LOCK:
        _JOBS[job_id] = {"events": [], "done": False, "error": None, "created": time.time()}
        _prune()
    return job_id


def _prune() -> None:
    now = time.time()
    stale = [jid for jid, j in _JOBS.items()
             if j["done"] and now - j["created"] > _MAX_AGE]
    for jid in stale:
        _JOBS.pop(jid, None)


def push(job_id: str, event: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["events"].append(event)


def finish(job_id: str, error: str | None = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["done"] = True
            job["error"] = error


def poll(job_id: str, after: int = 0):
    """Renvoie (evenements[after:], prochain_index, termine, erreur) ou None."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        events = job["events"][after:]
        return events, after + len(events), job["done"], job["error"]


def run_in_background(job_id: str, fn) -> None:
    """Lance `fn(job_id)` dans un thread demon ; capture toute exception."""
    def _target():
        try:
            fn(job_id)
            finish(job_id)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            finish(job_id, error=f"{type(exc).__name__}: {exc}")
    threading.Thread(target=_target, daemon=True).start()
