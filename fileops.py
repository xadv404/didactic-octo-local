"""
Outils fichier et shell, confines a l'espace de travail actif.

Chaque operation resout son chemin via workspace.resolve() : impossible de
sortir du dossier du chat. Le shell s'execute dans ce dossier, avec un delai
maximal, une sortie plafonnee et un garde-fou contre des commandes destructrices.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile
import shutil
import os
import re

import config
from workspace import resolve, rel_to_workspace, get_workspace

# Commandes refusees telles quelles — filet de securite minimal.
_DANGEROUS = [
    r"\brm\s+-rf?\s+(/|~|\$HOME)\b",
    r"\bmkfs\b", r"\bdd\s+if=", r":\(\)\s*\{", r"\bshutdown\b", r"\breboot\b",
    r"\bchmod\s+-R\s+000\b", r">\s*/dev/sd", r"\bmv\s+\S+\s+/dev/null\b",
]


def list_dir(path: str = ".") -> dict:
    target, err = resolve(path)
    if err:
        return {"ok": False, "error": err}
    if not target.exists():
        return {"ok": False, "error": "Dossier introuvable."}
    if not target.is_dir():
        return {"ok": False, "error": "Ce n'est pas un dossier."}
    entries = []
    for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        try:
            entries.append({"name": e.name, "type": "dir" if e.is_dir() else "file",
                            "size": e.stat().st_size if e.is_file() else None})
        except OSError:
            continue
    return {"ok": True, "path": rel_to_workspace(target), "entries": entries}


def read_file(path: str) -> dict:
    target, err = resolve(path)
    if err:
        return {"ok": False, "error": err}
    if not target.is_file():
        return {"ok": False, "error": "Fichier introuvable."}
    if target.stat().st_size > config.MAX_READ_BYTES:
        return {"ok": False, "error": f"Fichier trop volumineux (> {config.MAX_READ_BYTES} o)."}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": rel_to_workspace(target),
            "content": text, "lines": text.count("\n") + 1}


def write_file(path: str, content: str) -> dict:
    target, err = resolve(path)
    if err:
        return {"ok": False, "error": err}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content if content is not None else "", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": rel_to_workspace(target), "bytes": len(content or ""),
            "action": "modifie" if existed else "cree"}


def edit_file(path: str, find: str, replace: str) -> dict:
    """Remplace la premiere occurrence exacte de `find` par `replace`."""
    target, err = resolve(path)
    if err:
        return {"ok": False, "error": err}
    if not target.is_file():
        return {"ok": False, "error": "Fichier introuvable."}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if find not in text:
        return {"ok": False, "error": "Texte a remplacer introuvable."}
    count = text.count(find)
    try:
        target.write_text(text.replace(find, replace, 1), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": rel_to_workspace(target), "occurrences": count, "replaced": 1}


def make_dir(path: str) -> dict:
    target, err = resolve(path)
    if err:
        return {"ok": False, "error": err}
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": rel_to_workspace(target)}


def delete_path(path: str) -> dict:
    target, err = resolve(path)
    if err:
        return {"ok": False, "error": err}
    if target == get_workspace().resolve():
        return {"ok": False, "error": "Refus de supprimer la racine de l'espace."}
    if not target.exists():
        return {"ok": False, "error": "Chemin introuvable."}
    try:
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": rel_to_workspace(target), "deleted": True}


def move_path(src: str, dst: str) -> dict:
    s, err = resolve(src)
    if err:
        return {"ok": False, "error": f"source : {err}"}
    d, err = resolve(dst)
    if err:
        return {"ok": False, "error": f"destination : {err}"}
    if not s.exists():
        return {"ok": False, "error": "Source introuvable."}
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "from": rel_to_workspace(s), "to": rel_to_workspace(d)}


def _safe_extract(zip_path: Path, dest: Path) -> int:
    """Extrait un zip dans `dest` en refusant toute entree hors de `dest`."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if target != dest and dest not in target.parents:
                continue  # protection contre le « zip slip »
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                count += 1
    return count


def save_upload(filename: str, data: bytes, subdir: str = "") -> dict:
    """Enregistre un fichier envoye dans l'espace du chat ; extrait les zip."""
    name = os.path.basename(filename or "").strip() or "fichier"
    rel = f"{subdir.strip('/')}/{name}" if subdir else name
    target, err = resolve(rel)
    if err:
        return {"ok": False, "error": err}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    out = {"ok": True, "path": rel_to_workspace(target), "bytes": len(data),
           "name": name}
    if name.lower().endswith(".zip"):
        try:
            folder = target.with_suffix("")
            out["extracted"] = _safe_extract(target, folder)
            out["extracted_to"] = rel_to_workspace(folder)
        except zipfile.BadZipFile:
            out["extracted"] = 0
            out["error"] = "Archive zip illisible."
    return out


def run_command(command: str) -> dict:
    if not config.ALLOW_SHELL:
        return {"ok": False, "error": "Shell desactive (ATELIER_ALLOW_SHELL=0)."}
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "Commande vide."}
    for pattern in _DANGEROUS:
        if re.search(pattern, command):
            return {"ok": False, "error": "Commande refusee (garde-fou de securite)."}
    try:
        proc = subprocess.run(command, shell=True, cwd=str(get_workspace()),
                              capture_output=True, text=True, timeout=config.RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Delai depasse ({config.RUN_TIMEOUT}s)."}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    if len(out) > config.MAX_OUTPUT_CHARS:
        out = out[:config.MAX_OUTPUT_CHARS] + "\n[...sortie tronquee...]"
    return {"ok": proc.returncode == 0, "code": proc.returncode,
            "output": out.strip() or "(aucune sortie)"}
