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

## Installation

```bash
cd atelier-agents
pip install -r requirements.txt
python app.py
```

Ouvre `http://localhost:5000`, ou `http://IP_DU_VPS:5000` depuis une autre machine.

À la **première ouverture**, tu définis le mot de passe de l'atelier. Ensuite il
est demandé à chaque nouvelle session, et redemandé automatiquement tous les
15 jours.

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

### Machine modeste (ex. 12 Go RAM, 6 cœurs, CPU)

Reste sur un **7–8B quantifié** (~5 Go) : `qwen2.5-coder:7b`, `dolphin3`, ou
`dolphin-mistral` (le plus léger). La fenêtre de contexte et les threads sont
réglables pour maîtriser la RAM et le CPU :

| Variable | Rôle | Défaut |
|---|---|---|
| `OLLAMA_MODEL` | modèle Ollama | `qwen2.5-coder:7b` |
| `OLLAMA_NUM_CTX` | taille du contexte (⇒ RAM) | `8192` |
| `OLLAMA_NUM_THREAD` | threads CPU (`0` = auto) | `0` |

Un 14B/32B donne de meilleurs résultats mais demande plus de RAM et rame en CPU
— à réserver aux machines qui suivent.

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

## Recherche web

Le développeur dispose de l'outil `web_search`. Par défaut DuckDuckGo, sans clé
(deux interfaces tentées à la suite). **DuckDuckGo bloque fréquemment les IP de
datacenter** : sur un VPS la recherche peut échouer. Pour une recherche fiable,
prends une clé Brave (tier gratuit) :

```bash
export BRAVE_API_KEY="ta-cle"
python app.py
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

Les consignes de chaque agent sont en haut de `agents.py`
(`COORD_BRIEF_SYSTEM`, `ARCHITECT_SYSTEM`, `_developer_system`,
`REVIEWER_SYSTEM`, `COORD_DECISION_SYSTEM`). Les outils du développeur sont
dans `tools.py` (dictionnaire `TOOLS` + répartiteur `execute`). La persistance
et la mémoire sont dans `store.py`.

## Diagnostic

| Symptôme | Cause |
|---|---|
| Pastille rouge, « Ollama hors ligne » | `ollama serve` n'est pas lancé |
| « Modèle absent » | Le nom ne correspond pas — compare avec `ollama list` |
| Le développeur n'appelle pas d'outil | Modèle trop faible pour le format JSON — prends un modèle plus capable |
| Recherche web en échec | DuckDuckGo bloque l'IP — passe sur Brave |
| Mot de passe redemandé | Session de plus de 15 jours — c'est voulu |
| Très lent | Inférence CPU + nombreux appels par demande |
