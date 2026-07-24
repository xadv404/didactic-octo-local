"""
Conversations : chaque conversation vit dans SON PROPRE DOSSIER.

  <PROJECTS_ROOT>/<slug>-<id>/
      .atelier/
          conversation.json   messages du fil
          memory.json          resume + faits
          actions.json         journal de tout ce qui a ete fait
      workspace/               fichiers du projet (l'agent agit ici, les
                               envois et zip atterrissent ici)

Un index global (DATA_DIR) liste les conversations et resout id -> dossier,
pour un affichage rapide sans parcourir le disque.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import secrets
import shutil
import re

import config
import jsonstore as js

META = ".atelier"


# --------------------------------------------------------------------------
# Chemins d'une conversation
# --------------------------------------------------------------------------

def meta_dir(home) -> Path:
    return Path(home) / META


def conv_file(home) -> Path:
    return meta_dir(home) / "conversation.json"


def mem_file(home) -> Path:
    return meta_dir(home) / "memory.json"


def actions_file(home) -> Path:
    return meta_dir(home) / "actions.json"


def workspace_dir(home) -> Path:
    return Path(home) / "workspace"


def _slugify(title: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    return t[:40] or "chat"


def _new_home(title: str) -> Path:
    home = config.PROJECTS_ROOT / f"{_slugify(title)}-{secrets.token_hex(3)}"
    home.mkdir(parents=True, exist_ok=True)
    return home


# --------------------------------------------------------------------------
# Index global (registre)
# --------------------------------------------------------------------------

def _index_load() -> list:
    return js.read_json(config.INDEX_FILE, {"conversations": []}).get("conversations", [])


def _index_save(convs: list) -> None:
    js.write_json(config.INDEX_FILE, {"conversations": convs})


def _index_entry(conv: dict) -> dict:
    return {"id": conv["id"], "title": conv["title"], "home": conv["home"],
            "workspace": conv["workspace"], "created": conv["created"],
            "updated": conv["updated"], "message_count": len(conv["messages"])}


def index_upsert(conv: dict) -> None:
    convs = [c for c in _index_load() if c.get("id") != conv["id"]]
    convs.append(_index_entry(conv))
    _index_save(convs)


def home_of(conv_id: str):
    for c in _index_load():
        if c.get("id") == conv_id:
            return c.get("home")
    return None


def list_conversations() -> list:
    return sorted(_index_load(), key=lambda c: c.get("updated", 0), reverse=True)


# --------------------------------------------------------------------------
# Cycle de vie
# --------------------------------------------------------------------------

def new_conversation(title: str = "", workspace: str = "") -> dict:
    """Cree le dossier dedie de la conversation et ses fichiers internes."""
    with js._LOCK:
        conv_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        home = _new_home(title)
        meta_dir(home).mkdir(exist_ok=True)
        # workspace : sous-dossier dedie, ou dossier existant fourni (avance).
        wdir = Path(workspace).expanduser() if workspace else workspace_dir(home)
        wdir.mkdir(parents=True, exist_ok=True)
        now = js.now()
        conv = {
            "id": conv_id,
            "title": (title or "Nouvelle conversation").strip()[:80],
            "home": str(home),
            "workspace": str(wdir),
            "created": now, "updated": now, "seq": 0, "messages": [],
        }
        js.write_json(conv_file(home), conv)
        js.write_json(mem_file(home), {"conversation": conv_id, "summary": "", "facts": []})
        js.write_json(actions_file(home), {"conversation": conv_id, "actions": []})
        index_upsert(conv)
        return conv


def load_conversation(conv_id: str):
    home = home_of(conv_id)
    if not home:
        return None
    return js.read_json(conv_file(home), None)


def _save(conv: dict) -> None:
    js.write_json(conv_file(conv["home"]), conv)
    index_upsert(conv)


def rename_conversation(conv_id: str, title: str) -> bool:
    with js._LOCK:
        conv = load_conversation(conv_id)
        if not conv:
            return False
        conv["title"] = title.strip()[:80] or conv["title"]
        conv["updated"] = js.now()
        _save(conv)
        return True


def conversation_workspace(conv_id: str) -> str:
    conv = load_conversation(conv_id)
    return conv.get("workspace", "") if conv else ""


def set_conversation_workspace(conv_id: str, workspace: str) -> bool:
    with js._LOCK:
        conv = load_conversation(conv_id)
        if not conv:
            return False
        conv["workspace"] = workspace or str(workspace_dir(conv["home"]))
        conv["updated"] = js.now()
        _save(conv)
        return True


def delete_conversation(conv_id: str) -> bool:
    """Retire du registre et supprime le dossier de la conversation si c'est
    bien un dossier cree automatiquement sous PROJECTS_ROOT."""
    with js._LOCK:
        home = home_of(conv_id)
        _index_save([c for c in _index_load() if c.get("id") != conv_id])
        if home:
            try:
                root = config.PROJECTS_ROOT.resolve()
                hp = Path(home).resolve()
                if hp == root or root in hp.parents:
                    shutil.rmtree(hp, ignore_errors=True)
            except OSError:
                pass
        return True


def add_message(conv_id: str, role: str, content: str, **extra):
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
        _save(conv)
        return msg


def page_messages(conv_id: str, before_seq=None, limit: int = 25) -> dict:
    conv = load_conversation(conv_id)
    if conv is None:
        return {"messages": [], "has_more": False, "oldest_seq": None,
                "title": None, "workspace": "", "home": ""}
    msgs = conv["messages"]
    older = [m for m in msgs if m["seq"] < before_seq] if before_seq is not None else msgs
    window = older[-limit:]
    return {"messages": window, "has_more": len(older) > len(window),
            "oldest_seq": window[0]["seq"] if window else None,
            "title": conv["title"], "workspace": conv.get("workspace", ""),
            "home": conv.get("home", "")}
