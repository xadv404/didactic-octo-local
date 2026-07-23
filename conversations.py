"""
Conversations : creation, chargement, index, messages et pagination.

Chaque conversation est un fichier JSON dans CONV_DIR ; un index global liste
les conversations. Chaque chat porte son propre dossier de projet (workspace).
"""

from __future__ import annotations

from datetime import datetime
import secrets

import config
import jsonstore as js


def _conv_path(conv_id: str):
    return config.CONV_DIR / f"{conv_id}.json"


def _safe_id(conv_id: str) -> bool:
    return bool(conv_id) and all(c.isalnum() or c in "-_" for c in conv_id)


def new_conversation(title: str = "", workspace: str = "") -> dict:
    with js._LOCK:
        js.ensure_dirs()
        conv_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        now = js.now()
        conv = {
            "id": conv_id,
            "title": (title or "Nouvelle conversation").strip()[:80],
            "workspace": workspace or "",
            "created": now,
            "updated": now,
            "seq": 0,
            "messages": [],
        }
        js.write_json(_conv_path(conv_id), conv)
        index_upsert(conv)
        js.write_json(config.ACTIONS_DIR / f"{conv_id}.json",
                      {"conversation": conv_id, "actions": []})
        js.write_json(config.MEMORY_DIR / f"{conv_id}.json",
                      {"conversation": conv_id, "summary": "", "facts": []})
        return conv


def load_conversation(conv_id: str):
    if not _safe_id(conv_id):
        return None
    return js.read_json(_conv_path(conv_id), None)


def list_conversations() -> list:
    idx = js.read_json(config.INDEX_FILE, {"conversations": []})
    return sorted(idx.get("conversations", []),
                  key=lambda c: c.get("updated", 0), reverse=True)


def index_upsert(conv: dict) -> None:
    idx = js.read_json(config.INDEX_FILE, {"conversations": []})
    entry = {
        "id": conv["id"],
        "title": conv["title"],
        "workspace": conv.get("workspace", ""),
        "created": conv["created"],
        "updated": conv["updated"],
        "message_count": len(conv["messages"]),
    }
    convs = [c for c in idx.get("conversations", []) if c.get("id") != conv["id"]]
    convs.append(entry)
    js.write_json(config.INDEX_FILE, {"conversations": convs})


def rename_conversation(conv_id: str, title: str) -> bool:
    with js._LOCK:
        conv = load_conversation(conv_id)
        if not conv:
            return False
        conv["title"] = title.strip()[:80] or conv["title"]
        conv["updated"] = js.now()
        js.write_json(_conv_path(conv_id), conv)
        index_upsert(conv)
        return True


def conversation_workspace(conv_id: str) -> str:
    conv = load_conversation(conv_id)
    return conv.get("workspace", "") if conv else ""


def set_conversation_workspace(conv_id: str, workspace: str) -> bool:
    with js._LOCK:
        conv = load_conversation(conv_id)
        if not conv:
            return False
        conv["workspace"] = workspace or ""
        conv["updated"] = js.now()
        js.write_json(_conv_path(conv_id), conv)
        index_upsert(conv)
        return True


def delete_conversation(conv_id: str) -> bool:
    with js._LOCK:
        if not _safe_id(conv_id):
            return False
        for p in (_conv_path(conv_id), config.ACTIONS_DIR / f"{conv_id}.json",
                  config.MEMORY_DIR / f"{conv_id}.json"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        idx = js.read_json(config.INDEX_FILE, {"conversations": []})
        convs = [c for c in idx.get("conversations", []) if c.get("id") != conv_id]
        js.write_json(config.INDEX_FILE, {"conversations": convs})
        return True


def add_message(conv_id: str, role: str, content: str, **extra):
    """Ajoute un message et met a jour l'index. Renvoie le message stocke."""
    with js._LOCK:
        conv = load_conversation(conv_id)
        if conv is None:
            return None
        conv["seq"] = conv.get("seq", 0) + 1
        msg = {"seq": conv["seq"], "role": role, "content": content, "ts": js.now()}
        msg.update(extra)
        conv["messages"].append(msg)
        conv["updated"] = msg["ts"]
        if role == "user" and len([m for m in conv["messages"] if m["role"] == "user"]) == 1:
            conv["title"] = content.strip().split("\n")[0][:80] or conv["title"]
        js.write_json(_conv_path(conv_id), conv)
        index_upsert(conv)
        return msg


def page_messages(conv_id: str, before_seq=None, limit: int = 25) -> dict:
    """
    Renvoie au plus `limit` messages en ordre chronologique. Avec `before_seq`,
    ne renvoie que les messages plus anciens — c'est le chargement en remontant.
    """
    conv = load_conversation(conv_id)
    if conv is None:
        return {"messages": [], "has_more": False, "oldest_seq": None,
                "title": None, "workspace": ""}
    msgs = conv["messages"]
    older = [m for m in msgs if m["seq"] < before_seq] if before_seq is not None else msgs
    window = older[-limit:]
    return {
        "messages": window,
        "has_more": len(older) > len(window),
        "oldest_seq": window[0]["seq"] if window else None,
        "title": conv["title"],
        "workspace": conv.get("workspace", ""),
    }
