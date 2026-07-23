"""
Registre des outils du developpeur et repartiteur d'execution.

Declare les outils exposes au modele (nom, arguments, description), les relie
a leur implementation (fichiers, shell, web) et execute un appel en toute
securite — une exception dans un outil ne casse jamais la boucle de l'agent.
"""

from __future__ import annotations

import fileops
from websearch import web_search

TOOLS = {
    "list_dir":    {"args": ["path"],            "desc": "Lister le contenu d'un dossier."},
    "read_file":   {"args": ["path"],            "desc": "Lire un fichier texte."},
    "write_file":  {"args": ["path", "content"], "desc": "Creer ou ecraser un fichier."},
    "edit_file":   {"args": ["path", "find", "replace"], "desc": "Remplacer un extrait exact dans un fichier."},
    "make_dir":    {"args": ["path"],            "desc": "Creer un dossier."},
    "delete_path": {"args": ["path"],            "desc": "Supprimer un fichier ou dossier."},
    "move_path":   {"args": ["src", "dst"],      "desc": "Deplacer ou renommer."},
    "run_command": {"args": ["command"],         "desc": "Executer une commande shell dans l'espace."},
    "web_search":  {"args": ["query"],           "desc": "Rechercher sur le web (Chromium headless)."},
    "finish":      {"args": ["summary"],         "desc": "Terminer et resumer le travail accompli."},
}

_DISPATCH = {
    "list_dir": lambda a: fileops.list_dir(a.get("path", ".")),
    "read_file": lambda a: fileops.read_file(a.get("path", "")),
    "write_file": lambda a: fileops.write_file(a.get("path", ""), a.get("content", "")),
    "edit_file": lambda a: fileops.edit_file(a.get("path", ""), a.get("find", ""), a.get("replace", "")),
    "make_dir": lambda a: fileops.make_dir(a.get("path", "")),
    "delete_path": lambda a: fileops.delete_path(a.get("path", "")),
    "move_path": lambda a: fileops.move_path(a.get("src", ""), a.get("dst", "")),
    "run_command": lambda a: fileops.run_command(a.get("command", "")),
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
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def tools_manual() -> str:
    """Description des outils inseree dans la consigne du developpeur."""
    lines = []
    for name, spec in TOOLS.items():
        arglist = ", ".join(spec["args"]) if spec["args"] else "aucun"
        lines.append(f'- {name}({arglist}) : {spec["desc"]}')
    return "\n".join(lines)
