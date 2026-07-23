"""
Persistance, memoire et authentification pour l'Atelier.

Tout est ecrit dans des fichiers JSON sous DATA_DIR, decoupes par role
pour que rien ne soit jamais ecrase en bloc :

  data/
    auth.json                     mot de passe (hash) + reglages de session
    secret.key                    cle de signature des cookies (generee une fois)
    conversations/<id>.json       messages complets d'une conversation
    index/conversations.json      index de toutes les conversations
    index/actions/<id>.json       journal detaille de tout ce qui a ete fait
    memory/global.json            faits durables, tous fils confondus
    memory/<id>.json              memoire propre a une conversation

Ecritures atomiques (fichier temporaire + rename) et verrou global : le
serveur tourne en mode threade, deux requetes peuvent ecrire en meme temps.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import threading
import secrets
import json
import os
import time

from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ATELIER_DATA", BASE_DIR / "data"))

CONV_DIR = DATA_DIR / "conversations"
INDEX_DIR = DATA_DIR / "index"
ACTIONS_DIR = INDEX_DIR / "actions"
MEMORY_DIR = DATA_DIR / "memory"

AUTH_FILE = DATA_DIR / "auth.json"
SECRET_FILE = DATA_DIR / "secret.key"
INDEX_FILE = INDEX_DIR / "conversations.json"
GLOBAL_MEMORY_FILE = MEMORY_DIR / "global.json"

# Combien de jours une session reste valable avant de redemander le mot de passe.
SESSION_DAYS = 15

# Budgets de caractere injectes dans le contexte du modele.
HISTORY_CHAR_BUDGET = 9000
MEMORY_CHAR_BUDGET = 2500

_LOCK = threading.RLock()


# --------------------------------------------------------------------------
# Utilitaires bas niveau
# --------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _ensure_dirs() -> None:
    for d in (DATA_DIR, CONV_DIR, INDEX_DIR, ACTIONS_DIR, MEMORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    """Ecriture atomique : on ecrit a cote puis on remplace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{threading.get_ident()}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def init() -> None:
    """A appeler une fois au demarrage."""
    _ensure_dirs()
    if not INDEX_FILE.exists():
        _write_json(INDEX_FILE, {"conversations": []})
    if not GLOBAL_MEMORY_FILE.exists():
        _write_json(GLOBAL_MEMORY_FILE, {"facts": []})


# --------------------------------------------------------------------------
# Cle de session (persistante entre redemarrages)
# --------------------------------------------------------------------------

def secret_key() -> str:
    with _LOCK:
        _ensure_dirs()
        if SECRET_FILE.exists():
            return SECRET_FILE.read_text(encoding="utf-8").strip()
        key = secrets.token_hex(32)
        SECRET_FILE.write_text(key, encoding="utf-8")
        try:
            os.chmod(SECRET_FILE, 0o600)
        except OSError:
            pass
        return key


# --------------------------------------------------------------------------
# Authentification
# --------------------------------------------------------------------------

def has_password() -> bool:
    return bool(_read_json(AUTH_FILE, {}).get("hash"))


def set_password(password: str) -> None:
    """Definit (ou remplace) le mot de passe."""
    with _LOCK:
        _ensure_dirs()
        _write_json(AUTH_FILE, {
            "hash": generate_password_hash(password),
            "updated": _now(),
        })
        try:
            os.chmod(AUTH_FILE, 0o600)
        except OSError:
            pass


def check_password(password: str) -> bool:
    stored = _read_json(AUTH_FILE, {}).get("hash")
    if not stored:
        return False
    return check_password_hash(stored, password)


def session_expired(authed_at) -> bool:
    """Vrai si l'horodatage de connexion est absent ou vieux de plus de SESSION_DAYS."""
    if not authed_at:
        return True
    try:
        return (_now() - float(authed_at)) > SESSION_DAYS * 86400
    except (TypeError, ValueError):
        return True


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------

def _conv_path(conv_id: str) -> Path:
    return CONV_DIR / f"{conv_id}.json"


def _safe_id(conv_id: str) -> bool:
    return bool(conv_id) and all(c.isalnum() or c in "-_" for c in conv_id)


def new_conversation(title: str = "") -> dict:
    with _LOCK:
        _ensure_dirs()
        conv_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        now = _now()
        conv = {
            "id": conv_id,
            "title": (title or "Nouvelle conversation").strip()[:80],
            "created": now,
            "updated": now,
            "seq": 0,
            "messages": [],
        }
        _write_json(_conv_path(conv_id), conv)
        _index_upsert(conv)
        _write_json(ACTIONS_DIR / f"{conv_id}.json", {"conversation": conv_id, "actions": []})
        _write_json(MEMORY_DIR / f"{conv_id}.json",
                    {"conversation": conv_id, "summary": "", "facts": []})
        return conv


def load_conversation(conv_id: str):
    if not _safe_id(conv_id):
        return None
    return _read_json(_conv_path(conv_id), None)


def list_conversations() -> list:
    idx = _read_json(INDEX_FILE, {"conversations": []})
    convs = idx.get("conversations", [])
    return sorted(convs, key=lambda c: c.get("updated", 0), reverse=True)


def _index_upsert(conv: dict) -> None:
    idx = _read_json(INDEX_FILE, {"conversations": []})
    entry = {
        "id": conv["id"],
        "title": conv["title"],
        "created": conv["created"],
        "updated": conv["updated"],
        "message_count": len(conv["messages"]),
    }
    convs = [c for c in idx.get("conversations", []) if c.get("id") != conv["id"]]
    convs.append(entry)
    _write_json(INDEX_FILE, {"conversations": convs})


def rename_conversation(conv_id: str, title: str) -> bool:
    with _LOCK:
        conv = load_conversation(conv_id)
        if not conv:
            return False
        conv["title"] = title.strip()[:80] or conv["title"]
        conv["updated"] = _now()
        _write_json(_conv_path(conv_id), conv)
        _index_upsert(conv)
        return True


def delete_conversation(conv_id: str) -> bool:
    with _LOCK:
        if not _safe_id(conv_id):
            return False
        for p in (_conv_path(conv_id), ACTIONS_DIR / f"{conv_id}.json",
                  MEMORY_DIR / f"{conv_id}.json"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        idx = _read_json(INDEX_FILE, {"conversations": []})
        convs = [c for c in idx.get("conversations", []) if c.get("id") != conv_id]
        _write_json(INDEX_FILE, {"conversations": convs})
        return True


def add_message(conv_id: str, role: str, content: str, **extra) -> dict | None:
    """Ajoute un message et met a jour l'index. Renvoie le message stocke."""
    with _LOCK:
        conv = load_conversation(conv_id)
        if conv is None:
            return None
        conv["seq"] = conv.get("seq", 0) + 1
        msg = {
            "seq": conv["seq"],
            "role": role,
            "content": content,
            "ts": _now(),
        }
        msg.update(extra)
        conv["messages"].append(msg)
        conv["updated"] = msg["ts"]
        # Le titre suit la premiere question de l'utilisateur.
        if role == "user" and len([m for m in conv["messages"] if m["role"] == "user"]) == 1:
            conv["title"] = content.strip().split("\n")[0][:80] or conv["title"]
        _write_json(_conv_path(conv_id), conv)
        _index_upsert(conv)
        return msg


def page_messages(conv_id: str, before_seq: int | None = None, limit: int = 25) -> dict:
    """
    Renvoie au plus `limit` messages, les plus recents d'abord dans le stockage
    mais rendus en ordre chronologique. Avec `before_seq`, ne renvoie que les
    messages plus anciens — c'est le chargement en remontant.
    """
    conv = load_conversation(conv_id)
    if conv is None:
        return {"messages": [], "has_more": False, "oldest_seq": None}
    msgs = conv["messages"]
    if before_seq is not None:
        older = [m for m in msgs if m["seq"] < before_seq]
    else:
        older = msgs
    window = older[-limit:]
    has_more = len(older) > len(window)
    return {
        "messages": window,
        "has_more": has_more,
        "oldest_seq": window[0]["seq"] if window else None,
        "title": conv["title"],
    }


# --------------------------------------------------------------------------
# Journal des actions (« tout ce qui a ete fait »)
# --------------------------------------------------------------------------

def log_action(conv_id: str, entry: dict) -> None:
    with _LOCK:
        path = ACTIONS_DIR / f"{conv_id}.json"
        data = _read_json(path, {"conversation": conv_id, "actions": []})
        entry = {"ts": _now(), **entry}
        data["actions"].append(entry)
        _write_json(path, data)


def load_actions(conv_id: str) -> list:
    return _read_json(ACTIONS_DIR / f"{conv_id}.json", {"actions": []}).get("actions", [])


# --------------------------------------------------------------------------
# Memoire
# --------------------------------------------------------------------------

def remember(conv_id: str, text: str, scope: str = "conversation") -> None:
    """Ajoute un fait durable, au fil ou global."""
    text = (text or "").strip()
    if not text:
        return
    with _LOCK:
        fact = {"ts": _now(), "text": text[:600]}
        if scope == "global":
            data = _read_json(GLOBAL_MEMORY_FILE, {"facts": []})
            data.setdefault("facts", []).append({**fact, "conversation": conv_id})
            data["facts"] = data["facts"][-200:]
            _write_json(GLOBAL_MEMORY_FILE, data)
        else:
            path = MEMORY_DIR / f"{conv_id}.json"
            data = _read_json(path, {"conversation": conv_id, "summary": "", "facts": []})
            data.setdefault("facts", []).append(fact)
            data["facts"] = data["facts"][-100:]
            _write_json(path, data)


def set_summary(conv_id: str, summary: str) -> None:
    with _LOCK:
        path = MEMORY_DIR / f"{conv_id}.json"
        data = _read_json(path, {"conversation": conv_id, "summary": "", "facts": []})
        data["summary"] = (summary or "").strip()[:2000]
        _write_json(path, data)


def memory_block(conv_id: str) -> str:
    """
    Texte de memoire injecte en tete du contexte : resume du fil, faits du fil,
    puis faits globaux recents. Tronque au budget.
    """
    parts = []
    conv_mem = _read_json(MEMORY_DIR / f"{conv_id}.json", {})
    if conv_mem.get("summary"):
        parts.append("Resume de la conversation :\n" + conv_mem["summary"])
    facts = [f["text"] for f in conv_mem.get("facts", [])][-15:]
    if facts:
        parts.append("Faits retenus dans ce fil :\n- " + "\n- ".join(facts))
    gmem = _read_json(GLOBAL_MEMORY_FILE, {"facts": []}).get("facts", [])
    gfacts = [f["text"] for f in gmem][-10:]
    if gfacts:
        parts.append("Memoire generale :\n- " + "\n- ".join(gfacts))
    block = "\n\n".join(parts).strip()
    return block[:MEMORY_CHAR_BUDGET]


def history_block(conv_id: str, exclude_seq: int | None = None) -> str:
    """
    Historique lisible de la conversation en cours, borne au budget de
    caracteres (on garde les echanges les plus recents).
    """
    conv = load_conversation(conv_id)
    if conv is None:
        return ""
    lines = []
    for m in conv["messages"]:
        if exclude_seq is not None and m["seq"] == exclude_seq:
            continue
        who = "Utilisateur" if m["role"] == "user" else "Assistant"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{who} : {content}")
    text = "\n\n".join(lines)
    if len(text) > HISTORY_CHAR_BUDGET:
        text = "[...debut de conversation tronque...]\n\n" + text[-HISTORY_CHAR_BUDGET:]
    return text
