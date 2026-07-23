"""
Configuration centrale de l'Atelier.

Toutes les constantes et variables d'environnement vivent ici, pour que les
autres modules restent courts et qu'un reglage se change a un seul endroit.
"""

from __future__ import annotations

from pathlib import Path
import os

_env = os.environ.get

# --------------------------------------------------------------------------
# Ollama & modeles (un modele par role)
# --------------------------------------------------------------------------

OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")

# Modele de base (repli). qwen2.5:7b == 7b-instruct q4_K_M.
MODEL = _env("OLLAMA_MODEL", "qwen2.5-coder:7b")

MODEL_COORDINATEUR = _env("ATELIER_MODEL_COORDINATEUR", "qwen2.5:7b")   # reflechir
MODEL_ARCHITECTE   = _env("ATELIER_MODEL_ARCHITECTE",   "qwen2.5:7b")   # planifier
MODEL_DEVELOPPEUR  = _env("ATELIER_MODEL_DEVELOPPEUR",  MODEL)          # coder
MODEL_RELECTEUR    = _env("ATELIER_MODEL_RELECTEUR",    "qwen2.5:7b")   # relire
MODEL_MEMOIRE      = _env("ATELIER_MODEL_MEMOIRE",      MODEL_COORDINATEUR)

ROLE_MODELS = {
    "coordinateur": MODEL_COORDINATEUR,
    "architecte": MODEL_ARCHITECTE,
    "developpeur": MODEL_DEVELOPPEUR,
    "relecteur": MODEL_RELECTEUR,
    "memoire": MODEL_MEMOIRE,
}

# Ressources (adaptees a une petite machine ; genereux sur 24 Go / 8 cœurs).
NUM_CTX = int(_env("OLLAMA_NUM_CTX", "8192"))
NUM_THREAD = int(_env("OLLAMA_NUM_THREAD", "0"))  # 0 = auto

MAX_STEPS = int(_env("ATELIER_MAX_STEPS", "16"))
MAX_CYCLES = int(_env("ATELIER_MAX_CYCLES", "2"))
FILE_EXCERPT_CHARS = 6000

# --------------------------------------------------------------------------
# Donnees (plusieurs fichiers JSON, decoupes par role)
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(_env("ATELIER_DATA", str(BASE_DIR / "data")))

CONV_DIR = DATA_DIR / "conversations"
INDEX_DIR = DATA_DIR / "index"
ACTIONS_DIR = INDEX_DIR / "actions"
MEMORY_DIR = DATA_DIR / "memory"

AUTH_FILE = DATA_DIR / "auth.json"
SECRET_FILE = DATA_DIR / "secret.key"
INDEX_FILE = INDEX_DIR / "conversations.json"
GLOBAL_MEMORY_FILE = MEMORY_DIR / "global.json"
WORKSPACE_FILE = DATA_DIR / "workspace.json"

# --------------------------------------------------------------------------
# Authentification
# --------------------------------------------------------------------------

SESSION_DAYS = 15
# Mot de passe seme au premier lancement s'il n'y en a pas encore.
# Surchargeable par l'environnement ; modifiable ensuite en supprimant auth.json.
SEED_PASSWORD = _env("ATELIER_PASSWORD", "amexuhqia1337")

# --------------------------------------------------------------------------
# Contexte injecte dans le modele
# --------------------------------------------------------------------------

HISTORY_CHAR_BUDGET = 9000
MEMORY_CHAR_BUDGET = 2500

# --------------------------------------------------------------------------
# Espace de travail (un dossier par chat)
# --------------------------------------------------------------------------

DEFAULT_WORKSPACE = Path(
    _env("ATELIER_WORKSPACE", str(Path.home() / "Desktop"))
).expanduser()
PROJECTS_ROOT = Path(
    _env("ATELIER_PROJECTS", str(Path.home() / "AtelierProjets"))
).expanduser()

# --------------------------------------------------------------------------
# Outils fichier / shell
# --------------------------------------------------------------------------

ALLOW_SHELL = _env("ATELIER_ALLOW_SHELL", "1") != "0"
RUN_TIMEOUT = int(_env("ATELIER_RUN_TIMEOUT", "120"))
MAX_READ_BYTES = 400_000
MAX_OUTPUT_CHARS = 6000

# --------------------------------------------------------------------------
# Recherche web
# --------------------------------------------------------------------------

BRAVE_KEY = _env("BRAVE_API_KEY", "")
SEARCH_ENGINE = _env("ATELIER_SEARCH", "playwright")   # playwright | requests
SEARCH_RESULTS = 5
PW_TIMEOUT = int(_env("ATELIER_PW_TIMEOUT", "20000"))
PW_HEADLESS = _env("ATELIER_PW_HEADLESS", "1") != "0"
