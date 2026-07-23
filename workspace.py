"""
Espace de travail : un dossier de projet par chat, confine.

L'espace actif de la requete en cours est porte par un contextvar : chaque
conversation agit dans son propre dossier, isolee des autres. Toute resolution
de chemin refuse de sortir de la racine active.
"""

from __future__ import annotations

from pathlib import Path
import contextvars
import json
import os

import config

_ACTIVE = contextvars.ContextVar("active_workspace", default=None)


def set_active_workspace(path) -> None:
    _ACTIVE.set(str(path) if path else None)


def _global_default() -> Path:
    """Dossier par defaut suggere a la creation d'un chat (repli)."""
    try:
        raw = json.loads(config.WORKSPACE_FILE.read_text(encoding="utf-8"))
        return Path(raw["path"]).expanduser()
    except Exception:
        return config.DEFAULT_WORKSPACE


def get_workspace() -> Path:
    active = _ACTIVE.get()
    return Path(active) if active else _global_default()


def set_workspace(path_str: str):
    """Change le dossier par defaut global (suggestion a la creation)."""
    try:
        p = Path(path_str).expanduser().resolve()
    except (OSError, RuntimeError):
        return None, "Chemin invalide."
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, f"Creation impossible : {exc}"
    if not p.is_dir():
        return None, "Ce n'est pas un dossier."
    config.WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.WORKSPACE_FILE.write_text(json.dumps({"path": str(p)}), encoding="utf-8")
    return p, None


def prepare_workspace(folder: str):
    """
    Resout le dossier d'un chat : nom simple -> sous PROJECTS_ROOT, chemin
    absolu -> tel quel. Cree le dossier s'il manque.
    Renvoie (chemin, existait_deja, erreur).
    """
    folder = (folder or "").strip()
    if not folder:
        return None, False, "Indique un dossier de projet."
    p = Path(folder).expanduser()
    if not p.is_absolute():
        p = config.PROJECTS_ROOT / folder
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        return None, False, "Chemin invalide."
    existed = p.exists()
    if not existed:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, False, f"Creation impossible : {exc}"
    if not p.is_dir():
        return None, False, "Ce n'est pas un dossier."
    return p, existed, None


def resolve(rel: str):
    """Resout un chemin relatif dans l'espace actif, en refusant l'evasion."""
    root = get_workspace().resolve()
    rel = (rel or "").strip()
    candidate = (root / rel) if not os.path.isabs(rel) else Path(rel)
    try:
        candidate = candidate.resolve()
    except (OSError, RuntimeError):
        return None, "Chemin invalide."
    if candidate != root and root not in candidate.parents:
        return None, "Acces refuse : hors de l'espace de travail."
    return candidate, None


def rel_to_workspace(p) -> str:
    try:
        return str(Path(p).relative_to(get_workspace().resolve()))
    except ValueError:
        return str(p)
