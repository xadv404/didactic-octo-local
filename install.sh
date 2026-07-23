#!/usr/bin/env bash
#
# Installation de l'Atelier sur Ubuntu (VPS ou poste).
# Met en place : venv Python + modules, Chromium pour Playwright, Ollama et les
# modeles, puis genere un run.sh pret a lancer.
#
#   git clone <repo> atelier && cd atelier
#   bash install.sh
#   ./run.sh
#
set -euo pipefail

cd "$(dirname "$0")"
BOLD=$'\e[1m'; DIM=$'\e[2m'; OK=$'\e[32m'; NC=$'\e[0m'
say() { echo "${BOLD}==>${NC} $*"; }

# Modeles par role (surchargeables avant d'appeler le script).
MODEL_REASON="${ATELIER_MODEL_REASON:-qwen2.5:7b}"        # coordinateur/architecte/relecteur
MODEL_CODE="${ATELIER_MODEL_CODE:-qwen2.5-coder:7b}"      # developpeur
ATELIER_PASSWORD="${ATELIER_PASSWORD:-amexuhqia1337}"

# --------------------------------------------------------------------------
say "Paquets systeme (python venv, pip, curl)"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip curl ca-certificates
fi

# --------------------------------------------------------------------------
say "Environnement virtuel Python + modules"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# --------------------------------------------------------------------------
say "Navigateur Chromium pour Playwright (headless, pour la recherche web)"
# --with-deps installe aussi les libs systeme necessaires (sudo requis).
if ! python -m playwright install --with-deps chromium; then
  echo "${DIM}  install --with-deps a echoue (droits ?), tentative sans deps…${NC}"
  python -m playwright install chromium
  echo "${DIM}  si Chromium ne se lance pas : sudo python -m playwright install-deps chromium${NC}"
fi

# --------------------------------------------------------------------------
say "Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "${DIM}  deja installe${NC}"
fi

# Demarre le service si besoin (sur un VPS sans systemd, lance en tache de fond).
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  say "Demarrage d'Ollama"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q ollama; then
    sudo systemctl enable --now ollama || true
  fi
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    for _ in $(seq 1 30); do
      curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
      sleep 1
    done
  fi
fi

# --------------------------------------------------------------------------
say "Telechargement des modeles (~5 Go chacun)"
ollama pull "$MODEL_REASON"
ollama pull "$MODEL_CODE"

# --------------------------------------------------------------------------
say "Generation de run.sh"
cat > run.sh <<EOF
#!/usr/bin/env bash
# Lance l'Atelier. Regle ici les modeles, le mot de passe et les dossiers.
set -e
cd "\$(dirname "\$0")"
source .venv/bin/activate

export PLAYWRIGHT_BROWSERS_PATH="\${PLAYWRIGHT_BROWSERS_PATH:-\$HOME/.cache/ms-playwright}"
export ATELIER_PASSWORD="\${ATELIER_PASSWORD:-$ATELIER_PASSWORD}"

# Un modele par role (raisonnement vs code).
export ATELIER_MODEL_COORDINATEUR="\${ATELIER_MODEL_COORDINATEUR:-$MODEL_REASON}"
export ATELIER_MODEL_ARCHITECTE="\${ATELIER_MODEL_ARCHITECTE:-$MODEL_REASON}"
export ATELIER_MODEL_RELECTEUR="\${ATELIER_MODEL_RELECTEUR:-$MODEL_REASON}"
export OLLAMA_MODEL="\${OLLAMA_MODEL:-$MODEL_CODE}"

# Ressources (24 Go RAM / 8 cœurs : marge confortable).
export OLLAMA_NUM_CTX="\${OLLAMA_NUM_CTX:-8192}"

# Dossier des projets (un sous-dossier par chat y est cree).
export ATELIER_PROJECTS="\${ATELIER_PROJECTS:-\$HOME/AtelierProjets}"

# S'assure qu'Ollama tourne.
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 2
fi

exec python app.py
EOF
chmod +x run.sh

# --------------------------------------------------------------------------
echo
echo "${OK}${BOLD}Installation terminee.${NC}"
echo "  Lancer :        ${BOLD}./run.sh${NC}"
echo "  Ouvrir :        http://localhost:5000  (ou http://IP_DU_VPS:5000)"
echo "  Mot de passe :  ${BOLD}${ATELIER_PASSWORD}${NC}"
echo "  Test interne :  python selftest.py"
