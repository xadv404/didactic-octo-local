"""
Journal des actions et memoire, ranges dans le dossier de chaque conversation.

- Journal : « tout ce qui a ete fait » (outils, plans…) -> home/.atelier/actions.json
- Memoire du fil : resume + faits          -> home/.atelier/memory.json
- Memoire globale : faits tous fils confondus -> DATA_DIR/memory/global.json
- Historique : rendu lisible du fil, borne en taille.
"""

from __future__ import annotations

import config
import jsonstore as js
import conversations as convo


def _home(conv_id):
    return convo.home_of(conv_id)


# --------------------------------------------------------------------------
# Journal des actions
# --------------------------------------------------------------------------

def log_action(conv_id: str, entry: dict) -> None:
    home = _home(conv_id)
    if not home:
        return
    with js._LOCK:
        path = convo.actions_file(home)
        data = js.read_json(path, {"conversation": conv_id, "actions": []})
        data["actions"].append({"ts": js.now(), **entry})
        js.write_json(path, data)


def load_actions(conv_id: str) -> list:
    home = _home(conv_id)
    if not home:
        return []
    return js.read_json(convo.actions_file(home), {"actions": []}).get("actions", [])


# --------------------------------------------------------------------------
# Memoire
# --------------------------------------------------------------------------

def remember(conv_id: str, text: str, scope: str = "conversation") -> None:
    text = (text or "").strip()
    if not text:
        return
    with js._LOCK:
        fact = {"ts": js.now(), "text": text[:600]}
        if scope == "global":
            data = js.read_json(config.GLOBAL_MEMORY_FILE, {"facts": []})
            data.setdefault("facts", []).append({**fact, "conversation": conv_id})
            data["facts"] = data["facts"][-200:]
            js.write_json(config.GLOBAL_MEMORY_FILE, data)
            return
        home = _home(conv_id)
        if not home:
            return
        path = convo.mem_file(home)
        data = js.read_json(path, {"conversation": conv_id, "summary": "", "facts": []})
        data.setdefault("facts", []).append(fact)
        data["facts"] = data["facts"][-100:]
        js.write_json(path, data)


def set_summary(conv_id: str, summary: str) -> None:
    home = _home(conv_id)
    if not home:
        return
    with js._LOCK:
        path = convo.mem_file(home)
        data = js.read_json(path, {"conversation": conv_id, "summary": "", "facts": []})
        data["summary"] = (summary or "").strip()[:2000]
        js.write_json(path, data)


def memory_block(conv_id: str) -> str:
    """Resume du fil + faits du fil + faits globaux, borne au budget."""
    parts = []
    home = _home(conv_id)
    conv_mem = js.read_json(convo.mem_file(home), {}) if home else {}
    if conv_mem.get("summary"):
        parts.append("Resume de la conversation :\n" + conv_mem["summary"])
    facts = [f["text"] for f in conv_mem.get("facts", [])][-15:]
    if facts:
        parts.append("Faits retenus dans ce fil :\n- " + "\n- ".join(facts))
    gmem = js.read_json(config.GLOBAL_MEMORY_FILE, {"facts": []}).get("facts", [])
    gfacts = [f["text"] for f in gmem][-10:]
    if gfacts:
        parts.append("Memoire generale :\n- " + "\n- ".join(gfacts))
    return "\n\n".join(parts).strip()[:config.MEMORY_CHAR_BUDGET]


def history_block(conv_id: str, exclude_seq=None) -> str:
    """Historique lisible du fil, borne au budget (on garde le plus recent)."""
    conv = convo.load_conversation(conv_id)
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
    if len(text) > config.HISTORY_CHAR_BUDGET:
        text = "[...debut de conversation tronque...]\n\n" + text[-config.HISTORY_CHAR_BUDGET:]
    return text
