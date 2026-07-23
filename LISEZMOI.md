# Atelier — équipe d'agents locale, façon Claude Code

Un atelier de développement piloté par une **équipe d'agents** sur un modèle
**local** (Ollama). L'assistant agit **directement sur les fichiers de ton PC**
— lecture, écriture, shell, recherche web — sans passer par GitHub. Chaque
conversation est **gardée en mémoire** : l'IA relit l'historique et ce qu'elle a
déjà fait avant d'agir.

```
Coordinateur (réfléchit et pilote)
   → Architecte  : pose le plan (fichiers, étapes, risques)
   → Développeur : agit sur les fichiers / le shell / le web (boucle d'outils)
   → Relecteur   : vérifie ce qui a été livré
Coordinateur (décide) : terminé, ou nouvelle consigne → cycle suivant
```

## Ce qui a été ajouté

- **Équipe d'agents orchestrée.** Un coordinateur cadre la demande, mobilise
  l'architecte puis le développeur, fait relire, puis décide s'il faut relancer
  un cycle. Boucle jusqu'à `ATELIER_MAX_CYCLES` (2 par défaut).
- **Agent développeur outillé** (esprit Claude Code). Il agit vraiment sur les
  fichiers via une boucle *raisonnement → outil → observation* : `list_dir`,
  `read_file`, `write_file`, `edit_file`, `make_dir`, `delete_path`,
  `move_path`, `run_command` (shell), `web_search`, `finish`.
- **Espace de travail** confiné et choisi depuis l'interface (le Bureau par
  défaut). Toute opération fichier qui tenterait d'en sortir est refusée.
- **Historique + mémoire.** Chaque conversation est relue par l'IA. La mémoire
  distille des faits durables réinjectés au tour suivant.
- **Pagination.** 25 messages affichés par page, chargement des précédents en
  remontant dans le fil.
- **Indexation multi-JSON.** Toute la conversation et tout ce qui a été fait
  sont écrits dans plusieurs fichiers (voir *Données*).
- **Mot de passe + session cookie.** L'accès est protégé ; la session tient
  **15 jours** puis redemande le mot de passe.

## Installation sur un VPS Ubuntu (git clone + install.sh)

```bash
git clone <url-du-depot> atelier
cd atelier
bash install.sh      # venv + modules + Chromium (Playwright) + Ollama + modèles
./run.sh             # lance le serveur (démarre Ollama au besoin)
```

Puis ouvre `http://IP_DU_VPS:5000` (ou `http://localhost:5000`).

`install.sh` met tout en place et génère `run.sh` (qui porte les variables
d'environnement : modèles, mot de passe, dossiers). Réglages possibles avant
l'installation, p. ex. :

```bash
ATELIER_MODEL_CODE=qwen2.5-coder:7b ATELIER_MODEL_REASON=qwen2.5:7b bash install.sh
```

### Mot de passe

Le mot de passe par défaut est **`amexuhqia1337`** (semé au premier lancement
via `ATELIER_PASSWORD`). Pour le changer : édite `ATELIER_PASSWORD` dans
`run.sh`, ou supprime `data/auth.json` et rouvre la page pour en définir un
nouveau. La session tient **15 jours** puis le mot de passe est redemandé.

### Test interne

```bash
source .venv/bin/activate
python selftest.py   # vérifie tout, sans Ollama ni réseau
```

## Architecture (fichiers courts, ~60–300 lignes chacun)

| Fichier | Rôle |
|---|---|
| `config.py` | toutes les constantes et variables d'environnement |
| `jsonstore.py` | primitives JSON (verrou, écritures atomiques, init) |
| `auth.py` | mot de passe (hash) + session, semis du mot de passe |
| `conversations.py` | conversations, index, messages, pagination |
| `memory.py` | journal des actions + mémoire + historique |
| `workspace.py` | dossier par chat, résolution confinée |
| `fileops.py` | outils fichier + shell |
| `websearch.py` | recherche web (Playwright + repli requêtes) |
| `toolbox.py` | registre des outils + exécution |
| `prompts.py` | consignes système des agents |
| `llm.py` | accès Ollama + santé |
| `team.py` | orchestration (coordinateur + cycles) |
| `server.py` | routes Flask |
| `app.py` | point d'entrée |

## Modèle

Défaut : **`qwen2.5-coder:7b`** — orienté code, il suit bien mieux le protocole
d'outils (JSON) que `mistral:7b`, et tient dans ~5 Go (Q4). Récupère-le avec
`ollama pull qwen2.5-coder:7b` (vérifie avec `ollama list`).

Pour un modèle **moins censuré / moins tabou** (utile pour un agent qui touche
librement au système), bascule sans rien changer d'autre :

```bash
export OLLAMA_MODEL="dolphin3"        # Dolphin 3.0 (Llama 3.1 8B), non censuré
python app.py
```

N'importe quel modèle Ollama fonctionne (`export OLLAMA_MODEL="…"`). La pastille
du panneau gauche passe au rouge avec « Modèle absent » si le nom ne correspond
à rien d'installé.

### Un modèle par agent

Chaque rôle a **son propre modèle** : le raisonnement et la planification
tournent sur un modèle généraliste, le développement sur un modèle orienté
code. Les cartes d'étapes affichent le modèle utilisé, et la pastille passe au
rouge en listant les modèles à installer.

| Rôle | Variable | Défaut |
|---|---|---|
| Coordinateur (réfléchir) | `ATELIER_MODEL_COORDINATEUR` | `qwen2.5:7b` |
| Architecte (planifier) | `ATELIER_MODEL_ARCHITECTE` | `qwen2.5:7b` |
| Développeur (coder) | `ATELIER_MODEL_DEVELOPPEUR` | `qwen2.5-coder:7b` |
| Relecteur (relire) | `ATELIER_MODEL_RELECTEUR` | `qwen2.5:7b` |
| Mémoire (distiller) | `ATELIER_MODEL_MEMOIRE` | = coordinateur |

Les deux modèles par défaut à récupérer :

```bash
ollama pull qwen2.5:7b          # réflexion / plan / relecture
ollama pull qwen2.5-coder:7b    # développement
```

Ils pèsent ~5 Go chacun (≈10 Go au total). `install.sh` les récupère tout seul.

### VPS 24 Go RAM / 8 cœurs (CPU)

Confortable : les **deux** modèles 7B tiennent en RAM en même temps (~10 Go),
donc Ollama n'a pas à permuter entre le raisonnement et le code. Les défauts
conviennent tels quels ; `OLLAMA_NUM_CTX=8192` laisse de la marge (tu peux
monter à `12288`/`16384` si tu veux plus de contexte).

| Variable | Rôle | Défaut |
|---|---|---|
| `OLLAMA_MODEL` | modèle développeur / base | `qwen2.5-coder:7b` |
| `OLLAMA_NUM_CTX` | taille du contexte (⇒ RAM) | `8192` |
| `OLLAMA_NUM_THREAD` | threads CPU (`0` = auto) | `0` |

Pour un modèle **moins tabou** sur le dev, `export OLLAMA_MODEL=dolphin3`.
Un 14B (`qwen2.5-coder:14b`) passe sur 24 Go mais rame davantage en CPU pur.

## Un chat = un dossier de projet

À la création d'un chat, tu choisis son **dossier de projet** :

- un **nom simple** (ex. `mon-site`) → un nouveau dossier est créé sous la
  racine des projets (`~/AtelierProjets` par défaut) ;
- un **chemin absolu** (ex. `/home/moi/site`) → le dossier existant est ouvert
  (créé s'il n'existe pas encore).

Chaque chat agit **uniquement dans son dossier**. Le bouton *changer* (panneau
gauche) permet de rebrancher un chat sur un autre dossier. Le navigateur de
fichiers montre l'arborescence du chat courant ; un clic **joint un fichier** à
la demande.

Toutes les opérations fichier sont **confinées au dossier du chat** : un chemin
qui tenterait d'en sortir est refusé. Le shell s'exécute dans ce dossier, avec
un délai maximal et un garde-fou contre quelques commandes destructrices.

Variables d'environnement utiles :

| Variable | Rôle | Défaut |
|---|---|---|
| `ATELIER_PROJECTS` | racine des dossiers créés par nom | `~/AtelierProjets` |
| `ATELIER_WORKSPACE` | dossier par défaut suggéré | `~/Desktop` |
| `ATELIER_ALLOW_SHELL` | `0` pour couper le shell | `1` |
| `ATELIER_RUN_TIMEOUT` | délai max d'une commande (s) | `120` |
| `ATELIER_MAX_STEPS` | tours d'outils max par cycle | `16` |
| `ATELIER_MAX_CYCLES` | cycles d'équipe max | `2` |
| `ATELIER_DATA` | dossier des données | `./data` |

## Ajouter à l'écran d'accueil (iOS / Android)

L'atelier est une **PWA** : tu peux l'installer comme une app.

- **iPhone / iPad (Safari)** : ouvre l'atelier, touche le bouton *Partager* →
  **« Sur l'écran d'accueil »**. L'icône « A. » apparaît ; l'app se lance en
  **plein écran** (sans barre Safari), avec la barre d'état gérée et la zone du
  *home indicator* respectée.
- **Android (Chrome)** : menu ⋮ → **« Installer l'application »**.

Tout est déjà en place (`manifest.webmanifest`, balises Apple, icônes dans
`static/`). L'app installée garde **sa propre session** : à la première
ouverture depuis l'écran d'accueil, saisis le mot de passe une fois — il tient
ensuite 15 jours, comme dans le navigateur.

## Recherche web (Playwright + Chromium headless)

Le développeur dispose de l'outil `web_search`. Par défaut, il interroge
DuckDuckGo dans un **Chromium headless** piloté par **Playwright** — un vrai
navigateur, ce qui passe bien mieux les blocages qu'une simple requête HTTP
(important sur un VPS). `install.sh` installe Chromium (`playwright install
chromium`). En cas d'échec, l'agent bascule sur des requêtes HTTP directes.

| Variable | Rôle | Défaut |
|---|---|---|
| `ATELIER_SEARCH` | `playwright` ou `requests` | `playwright` |
| `ATELIER_PW_TIMEOUT` | délai de chargement (ms) | `20000` |
| `ATELIER_PW_HEADLESS` | `0` pour voir le navigateur | `1` |

Pour une recherche encore plus fiable, une clé Brave (tier gratuit) prend le
dessus si elle est fournie :

```bash
export BRAVE_API_KEY="ta-cle"
```

## Données

Tout est écrit sous `data/` (ignoré par git), découpé par rôle pour que rien ne
soit jamais écrasé en bloc :

```
data/
  auth.json                     mot de passe (hash) + réglages
  secret.key                    clé de signature des cookies de session
  conversations/<id>.json       messages complets d'une conversation
  index/conversations.json      index de toutes les conversations
  index/actions/<id>.json       journal détaillé de tout ce qui a été fait
  memory/global.json            faits durables, tous fils confondus
  memory/<id>.json              résumé et faits propres à une conversation
```

## Durée

Beaucoup d'appels au modèle par demande (coordination, plan, plusieurs tours
d'outils, relecture, éventuel second cycle). Sur un 7B en CPU, compte
**plusieurs minutes**. Rien n'est perdu pendant l'attente : chaque token
s'affiche à mesure, et chaque appel d'outil est tracé en direct.

## Sécurité

- Accès protégé par mot de passe (session cookie, 15 jours).
- Opérations fichier confinées à l'espace de travail.
- Le **shell reste puissant** : il exécute des commandes réelles sur ta machine,
  dans l'espace de travail. Coupe-le avec `ATELIER_ALLOW_SHELL=0` si tu ne veux
  pas de cette capacité. Ne rends pas le port `5000` accessible à des tiers non
  fiables.

Restreindre le port à ton IP (Windows) :

```powershell
New-NetFirewallRule -DisplayName "Atelier" -Direction Inbound -LocalPort 5000 `
  -Protocol TCP -RemoteAddress TON.IP.ICI -Action Allow
```

## Régler l'équipe

Les consignes de chaque agent sont dans `prompts.py`. L'orchestration (cycles,
décision, boucle d'outils) est dans `team.py`. Les outils du développeur sont
déclarés dans `toolbox.py` (`TOOLS` + `execute`) et implémentés dans
`fileops.py` / `websearch.py`. La persistance et la mémoire sont dans
`conversations.py` et `memory.py`.

## Diagnostic

| Symptôme | Cause |
|---|---|
| Pastille rouge, « Ollama hors ligne » | `ollama serve` n'est pas lancé |
| « Modèle absent » | Le nom ne correspond pas — compare avec `ollama list` |
| Le développeur n'appelle pas d'outil | Modèle trop faible pour le format JSON — prends un modèle plus capable |
| Recherche web en échec | DuckDuckGo bloque l'IP — passe sur Brave |
| Mot de passe redemandé | Session de plus de 15 jours — c'est voulu |
| Très lent | Inférence CPU + nombreux appels par demande |
