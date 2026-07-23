"""
Outils de l'equipe d'agents : systeme de fichiers, shell et recherche web.

L'idee est celle de Claude Code, mais en local et sans GitHub : les agents
agissent directement sur les fichiers d'un dossier de travail (l'« espace »)
choisi par l'utilisateur — par defaut le Bureau.

Toutes les operations fichier sont confinees a la racine de l'espace : un
chemin qui tenterait d'en sortir est refuse. Le shell, lui, ne peut pas etre
confine de facon absolue ; il s'execute dans l'espace, avec un delai maximal,
une sortie plafonnee et un garde-fou contre quelques commandes destructrices.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus  # noqa: F401  (garde la parite avec l'ancien app)
import contextvars
import subprocess
import shutil
import json
import html as htmllib
import re
import os

import requests

from store import DATA_DIR

WORKSPACE_FILE = DATA_DIR / "workspace.json"

DEFAULT_WORKSPACE = Path(
    os.environ.get("ATELIER_WORKSPACE", str(Path.home() / "Desktop"))
).expanduser()

# Racine ou aterrissent les projets crees par simple nom (chaque chat = un dossier).
PROJECTS_ROOT = Path(
    os.environ.get("ATELIER_PROJECTS", str(Path.home() / "AtelierProjets"))
).expanduser()

# Espace actif pour la requete en cours : chaque conversation a le sien.
_ACTIVE = contextvars.ContextVar("active_workspace", default=None)


def set_active_workspace(path) -> None:
    """Fixe l'espace de travail de la requete/generation en cours."""
    _ACTIVE.set(str(path) if path else None)

ALLOW_SHELL = os.environ.get("ATELIER_ALLOW_SHELL", "1") != "0"
RUN_TIMEOUT = int(os.environ.get("ATELIER_RUN_TIMEOUT", "120"))

MAX_READ_BYTES = 400_000
MAX_OUTPUT_CHARS = 6000
SEARCH_RESULTS = 5

BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "")

# Commandes qu'on refuse d'executer telles quelles — filet de securite minimal.
_DANGEROUS = [
    r"\brm\s+-rf?\s+(/|~|\$HOME)\b",
    r"\bmkfs\b", r"\bdd\s+if=", r":\(\)\s*\{", r"\bshutdown\b", r"\breboot\b",
    r"\bchmod\s+-R\s+000\b", r">\s*/dev/sd", r"\bmv\s+\S+\s+/dev/null\b",
]


# --------------------------------------------------------------------------
# Espace de travail
# --------------------------------------------------------------------------

def _global_default() -> Path:
    """Dossier par defaut suggere a la creation d'un chat (repli)."""
    try:
        raw = json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
        return Path(raw["path"]).expanduser()
    except Exception:
        return DEFAULT_WORKSPACE


def get_workspace() -> Path:
    """Espace actif de la requete en cours, sinon le defaut global."""
    active = _ACTIVE.get()
    return Path(active) if active else _global_default()


def set_workspace(path_str: str) -> tuple[Path | None, str | None]:
    """Change le dossier par defaut global (suggestion a la creation d'un chat)."""
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
    WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_FILE.write_text(json.dumps({"path": str(p)}), encoding="utf-8")
    return p, None


def prepare_workspace(folder: str) -> tuple[Path | None, bool, str | None]:
    """
    Resout le dossier d'un chat : soit un dossier existant, soit un nouveau.
    Un chemin absolu (ou ~) est pris tel quel ; un simple nom atterrit sous
    PROJECTS_ROOT. Le dossier est cree s'il n'existe pas.
    Renvoie (chemin, existait_deja, erreur).
    """
    folder = (folder or "").strip()
    if not folder:
        return None, False, "Indique un dossier de projet."
    p = Path(folder).expanduser()
    if not p.is_absolute():
        p = PROJECTS_ROOT / folder
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


def _resolve(rel: str) -> tuple[Path | None, str | None]:
    """Resout un chemin relatif dans l'espace, en refusant toute evasion."""
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


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(get_workspace().resolve()))
    except ValueError:
        return str(p)


# --------------------------------------------------------------------------
# Outils fichier
# --------------------------------------------------------------------------

def list_dir(path: str = ".") -> dict:
    target, err = _resolve(path)
    if err:
        return {"ok": False, "error": err}
    if not target.exists():
        return {"ok": False, "error": "Dossier introuvable."}
    if not target.is_dir():
        return {"ok": False, "error": "Ce n'est pas un dossier."}
    entries = []
    for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        try:
            entries.append({
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
                "size": e.stat().st_size if e.is_file() else None,
            })
        except OSError:
            continue
    return {"ok": True, "path": _rel(target), "entries": entries}


def read_file(path: str) -> dict:
    target, err = _resolve(path)
    if err:
        return {"ok": False, "error": err}
    if not target.is_file():
        return {"ok": False, "error": "Fichier introuvable."}
    if target.stat().st_size > MAX_READ_BYTES:
        return {"ok": False, "error": f"Fichier trop volumineux (> {MAX_READ_BYTES} o)."}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": _rel(target), "content": text, "lines": text.count("\n") + 1}


def write_file(path: str, content: str) -> dict:
    target, err = _resolve(path)
    if err:
        return {"ok": False, "error": err}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content if content is not None else "", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": _rel(target), "bytes": len(content or ""),
            "action": "modifie" if existed else "cree"}


def edit_file(path: str, find: str, replace: str) -> dict:
    """Remplace la premiere occurrence exacte de `find` par `replace`."""
    target, err = _resolve(path)
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
    new = text.replace(find, replace, 1)
    try:
        target.write_text(new, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": _rel(target), "occurrences": count, "replaced": 1}


def make_dir(path: str) -> dict:
    target, err = _resolve(path)
    if err:
        return {"ok": False, "error": err}
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": _rel(target)}


def delete_path(path: str) -> dict:
    target, err = _resolve(path)
    if err:
        return {"ok": False, "error": err}
    if target == get_workspace().resolve():
        return {"ok": False, "error": "Refus de supprimer la racine de l'espace."}
    if not target.exists():
        return {"ok": False, "error": "Chemin introuvable."}
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": _rel(target), "deleted": True}


def move_path(src: str, dst: str) -> dict:
    s, err = _resolve(src)
    if err:
        return {"ok": False, "error": f"source : {err}"}
    d, err = _resolve(dst)
    if err:
        return {"ok": False, "error": f"destination : {err}"}
    if not s.exists():
        return {"ok": False, "error": "Source introuvable."}
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "from": _rel(s), "to": _rel(d)}


def run_command(command: str) -> dict:
    if not ALLOW_SHELL:
        return {"ok": False, "error": "Shell desactive (ATELIER_ALLOW_SHELL=0)."}
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "Commande vide."}
    for pattern in _DANGEROUS:
        if re.search(pattern, command):
            return {"ok": False, "error": "Commande refusee (garde-fou de securite)."}
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(get_workspace()),
            capture_output=True, text=True, timeout=RUN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Delai depasse ({RUN_TIMEOUT}s)."}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n[...sortie tronquee...]"
    return {"ok": proc.returncode == 0, "code": proc.returncode,
            "output": out.strip() or "(aucune sortie)"}


# --------------------------------------------------------------------------
# Recherche web (reprise de l'ancien app, exposee comme outil)
# --------------------------------------------------------------------------

def _search_brave(query):
    r = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"},
        params={"q": query, "count": SEARCH_RESULTS}, timeout=20,
    )
    r.raise_for_status()
    out = []
    for item in r.json().get("web", {}).get("results", [])[:SEARCH_RESULTS]:
        out.append({"title": item.get("title", ""),
                    "snippet": re.sub(r"<[^>]+>", "", item.get("description", "")),
                    "url": item.get("url", "")})
    return out


def _search_ddg_lite(query):
    r = requests.post(
        "https://lite.duckduckgo.com/lite/", data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                 "Referer": "https://lite.duckduckgo.com/"}, timeout=20,
    )
    r.raise_for_status()
    clean = lambda s: htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    links = re.findall(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
    snips = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', r.text, re.S)
    out = []
    for i, (url, title) in enumerate(links[:SEARCH_RESULTS]):
        out.append({"title": clean(title),
                    "snippet": clean(snips[i]) if i < len(snips) else "", "url": url})
    return out


def _search_ddg_html(query):
    r = requests.post(
        "https://html.duckduckgo.com/html/", data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=20,
    )
    r.raise_for_status()
    clean = lambda s: htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>.*?'
        r'class="result__snippet".*?>(.*?)</a>', r.text, re.S)
    out = []
    for url, title, snippet in blocks[:SEARCH_RESULTS]:
        out.append({"title": clean(title), "snippet": clean(snippet), "url": url})
    return out


def web_search(query: str) -> dict:
    providers = ([("Brave", _search_brave)] if BRAVE_KEY
                 else [("DuckDuckGo lite", _search_ddg_lite),
                       ("DuckDuckGo html", _search_ddg_html)])
    problems = []
    for name, fn in providers:
        try:
            results = fn(query)
            if results:
                return {"ok": True, "query": query, "results": results}
            problems.append(f"{name}: aucun resultat")
        except Exception as exc:
            problems.append(f"{name}: {type(exc).__name__}")
    return {"ok": False, "query": query, "results": [], "error": " / ".join(problems)}


# --------------------------------------------------------------------------
# Registre : declaration des outils pour le modele + repartiteur d'execution
# --------------------------------------------------------------------------

TOOLS = {
    "list_dir":   {"args": ["path"],            "desc": "Lister le contenu d'un dossier."},
    "read_file":  {"args": ["path"],            "desc": "Lire un fichier texte."},
    "write_file": {"args": ["path", "content"], "desc": "Creer ou ecraser un fichier."},
    "edit_file":  {"args": ["path", "find", "replace"], "desc": "Remplacer un extrait exact dans un fichier."},
    "make_dir":   {"args": ["path"],            "desc": "Creer un dossier."},
    "delete_path":{"args": ["path"],            "desc": "Supprimer un fichier ou dossier."},
    "move_path":  {"args": ["src", "dst"],      "desc": "Deplacer ou renommer."},
    "run_command":{"args": ["command"],         "desc": "Executer une commande shell dans l'espace."},
    "web_search": {"args": ["query"],           "desc": "Rechercher sur le web."},
    "finish":     {"args": ["summary"],         "desc": "Terminer et resumer le travail accompli."},
}

_DISPATCH = {
    "list_dir": lambda a: list_dir(a.get("path", ".")),
    "read_file": lambda a: read_file(a.get("path", "")),
    "write_file": lambda a: write_file(a.get("path", ""), a.get("content", "")),
    "edit_file": lambda a: edit_file(a.get("path", ""), a.get("find", ""), a.get("replace", "")),
    "make_dir": lambda a: make_dir(a.get("path", "")),
    "delete_path": lambda a: delete_path(a.get("path", "")),
    "move_path": lambda a: move_path(a.get("src", ""), a.get("dst", "")),
    "run_command": lambda a: run_command(a.get("command", "")),
    "web_search": lambda a: web_search(a.get("query", "")),
}


def execute(name: str, args: dict) -> dict:
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "error": f"Outil inconnu : {name}"}
    if not isinstance(args, dict):
        return {"ok": False, "error": "Arguments invalides."}
    try:
        return fn(args)
    except Exception as exc:  # noqa: BLE001 — on ne veut jamais casser la boucle
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def tools_manual() -> str:
    """Description des outils inseree dans la consigne du developpeur."""
    lines = []
    for name, spec in TOOLS.items():
        arglist = ", ".join(spec["args"]) if spec["args"] else "aucun"
        lines.append(f'- {name}({arglist}) : {spec["desc"]}')
    return "\n".join(lines)
