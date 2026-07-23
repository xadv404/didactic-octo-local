"""
Atelier — equipe d'agents locale sur modele Ollama, facon Claude Code.

Point d'entree. Le code est reparti en petits modules :
  config, jsonstore, auth, conversations, memory, workspace, fileops,
  websearch, toolbox, prompts, llm, team, server.
"""

import config
import workspace as ws
import websearch
from server import app

if __name__ == "__main__":
    print(f"  modeles   : coord={config.MODEL_COORDINATEUR} archi={config.MODEL_ARCHITECTE} "
          f"dev={config.MODEL_DEVELOPPEUR} relect={config.MODEL_RELECTEUR}")
    print(f"  espace    : {ws.get_workspace()}  (projets : {config.PROJECTS_ROOT})")
    print(f"  recherche : {websearch.search_label()}")
    print(f"  donnees   : {config.DATA_DIR}")
    print(f"  session   : {config.SESSION_DAYS} jours")
    print("  ecoute    : http://0.0.0.0:5000\n")
    app.run(host="0.0.0.0", port=5000, threaded=True)
