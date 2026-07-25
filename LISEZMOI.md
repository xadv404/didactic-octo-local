# Atelier — chatbot (Electron ou ligne de commande)

Un chatbot **simple**, branché sur un modèle Ollama **local**, utilisable en
app de bureau (Electron) **ou** en ligne de commande — les deux partagent le
même moteur et le même format de conversation. Pas de site web, pas de
plusieurs agents qui se relaient : un modèle, une conversation par projet, et
une recherche web activable au coup par coup.

## Installation

Il faut [Node.js](https://nodejs.org) (18+) et [Ollama](https://ollama.com)
installés, avec un modèle téléchargé :

```bash
ollama pull qwen2.5:7b
```

Puis, dans le dossier du projet :

```bash
npm install
```

### App de bureau

```bash
npm start
```

Au lancement, une **fenêtre de sélection de dossier** s'ouvre : choisis le
dossier du projet sur lequel tu veux travailler (ou annule pour reprendre le
dernier utilisé). Ollama doit tourner (`ollama serve`, ou il démarre tout seul
selon l'installation).

### Ligne de commande

```bash
npm run chat -- .          # dossier courant
# ou : node cli.js /chemin/vers/un/projet
# ou, apres un `npm link` (installation globale) : atelier /chemin/vers/un/projet
```

```
Atelier — /chemin/vers/un/projet
Modele : qwen2.5:7b  ·  Ollama : http://localhost:11434
Tape /help pour les commandes, /exit pour quitter.

> explique-moi ce que fait index.js
...
> /web quelle version de node est recommandee pour ce projet ?
🌐 Recherche…
  [1] ...
...
```

Commandes dans le chat :

| Commande | Effet |
|---|---|
| `/web <message>` | Recherche web pour **ce message uniquement** (comme le bouton 🌐 de l'app) |
| `/web on` | Active la recherche pour **tous les messages suivants**, sans avoir a la redemander |
| `/web off` | Revient au mode message par message (defaut) |
| `/clear` | Efface l'historique de ce projet |
| `/help` | Affiche l'aide |
| `/exit` ou `/quit` (ou Ctrl+D) | Quitte |

Options : `--model <nom>` et `--url <adresse>` (mémorisées pour la prochaine
fois, dans `~/.atelier-cli/settings.json`).

Un même dossier de projet garde **la même conversation** qu'on l'ouvre en CLI
ou dans l'app de bureau (`<dossier>/.atelier-chat/history.json`).

## Le dossier de projet

Chaque lancement (ou clic sur **📁** en haut) choisit un dossier de projet.
Ce dossier sert à deux choses :

- **La conversation de ce projet** est sauvegardée dedans
  (`<dossier>/.atelier-chat/history.json`) et rechargée à la prochaine
  ouverture — changer de dossier, c'est changer de conversation.
- **Le modèle peut lire et écrire des fichiers** de ce dossier quand c'est
  utile à ta demande (ex. « résume le fichier notes.md », « écris un script
  qui... », « corrige la faute dans config.txt »). Il n'agit **jamais** en
  dehors de ce dossier — un chemin qui tenterait d'en sortir est refusé.

Chaque appel d'outil (lecture, écriture, listing) s'affiche dans le chat au
moment où il se produit, avec son résultat — rien ne se passe en silence.

Pas de commande shell, pas de suppression de fichiers : seulement lister,
lire, écrire et remplacer un extrait dans un fichier existant.

## Le bouton Web

À côté de la zone de saisie, le bouton **🌐 Web** n'agit **que pour le message
en cours** : s'il est actif quand tu appuies sur Envoyer, ce message déclenche
une recherche DuckDuckGo dont les résultats sont injectés au modèle avant sa
réponse. Par défaut, le bouton se **désactive automatiquement** après l'envoi
— il faut le recliquer à chaque fois que tu veux une recherche pour un nouveau
message.

Coche **« Toujours »** à côté du bouton pour que la recherche s'active
**automatiquement à chaque message**, sans avoir à recliquer — pratique pour
une session où tu veux systématiquement des informations à jour. Décoche pour
revenir au mode message par message. En CLI, l'équivalent est `/web on` et
`/web off` (voir plus bas).

La recherche passe par une **fenêtre Chromium cachée** (`browserSearch.js`) :
Electron embarque déjà Chromium, donc pas de dépendance supplémentaire — la
page est réellement chargée et rendue (headless, jamais affichée), ce qui
passe mieux les blocages qu'une simple requête HTTP. En cas d'échec, repli
automatique sur une requête HTTP directe (`search.js`). Pour forcer ce repli
seul : `ATELIER_SEARCH=fetch npm start`.

## Réglages

L'icône ⚙ (en haut) ouvre un panneau pour changer :

- **Adresse Ollama** — `http://localhost:11434` par défaut. Peut pointer vers
  un Ollama distant (ex. un VPS) en mettant son IP.
- **Modèle** — le nom exact tel qu'il apparaît dans `ollama list` (ex.
  `qwen2.5:7b`, `qwen2.5-coder:7b`, `dolphin3` pour un modèle moins censuré).

La pastille en haut à gauche indique si Ollama est joignable et si le modèle
choisi est bien installé.

## Architecture (fichiers courts)

| Fichier | Rôle |
|---|---|
| `main.js` | processus principal Electron : sélection du projet, fenêtre, câblage IPC |
| `preload.js` | pont sécurisé entre la fenêtre et `main.js` |
| `cli.js` | chatbot en ligne de commande (même moteur, sans Electron) |
| `ollama.js` | construction des messages + streaming de la réponse |
| `agent.js` | consigne système « outils » + extraction des appels d'outil |
| `tools.js` | lecture/écriture de fichiers confinée au dossier de projet |
| `browserSearch.js` | recherche via Chromium headless (fenêtre Electron cachée) |
| `search.js` | recherche web DuckDuckGo par requête HTTP directe (repli, utilisée aussi par la CLI) |
| `store.js` | réglages + historique, persistés en JSON |
| `renderer/index.html` | structure de la fenêtre |
| `renderer/renderer.js` | logique de l'interface (chat, outils, Web, réglages) |
| `renderer/style.css` | thème sombre |
| `selftest.js` | tests des modules purs, sans Electron ni réseau |

`ollama.js`, `search.js`, `store.js`, `tools.js` et `agent.js` ne dépendent pas
d'Electron : ils sont testables avec du Node pur. Seul `browserSearch.js`
nécessite Electron (`BrowserWindow`), puisque c'est tout son propos.

```bash
npm test          # ou : node selftest.js
```

## Comment ça marche (un seul modèle, pas d'étages)

Le modèle répond normalement. S'il a besoin de lire ou écrire un fichier, il
termine sa réponse par un bloc JSON `{"tool": "...", "args": {...}}` ; `main.js`
exécute l'outil, renvoie le résultat au modèle, qui continue — jusqu'à une
réponse normale (sans bloc JSON) ou 8 tours maximum. Ce n'est **pas** un
pipeline à plusieurs agents : c'est le même modèle, le même rôle, qui boucle
brièvement quand c'est utile.

## Sécurité

La fenêtre tourne avec `contextIsolation` et `sandbox` activés, sans accès
Node direct au contenu web — seules les fonctions explicitement exposées dans
`preload.js` sont disponibles côté interface. Les outils fichier sont confinés
au dossier de projet choisi ; aucun accès shell.

## Diagnostic

| Symptôme | Cause |
|---|---|
| Pastille rouge, « Ollama hors ligne » | `ollama serve` n'est pas lancé, ou mauvaise adresse dans les réglages |
| « Modèle absent » | Le nom ne correspond à rien d'installé — vérifie avec `ollama list` |
| Recherche en échec | DuckDuckGo peut bloquer certaines IP (rare sur un poste résidentiel) |
| Rien ne se passe au clic sur Web | Le bouton ne vaut que pour le *prochain* envoi — il faut cliquer juste avant Envoyer |
| Le modèle n'utilise jamais les outils | Modèle trop faible pour suivre le format JSON — essaie `qwen2.5-coder:7b` |
