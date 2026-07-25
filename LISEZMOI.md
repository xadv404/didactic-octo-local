# Atelier — chatbot de bureau (Electron)

Un chatbot **simple** en application de bureau (Electron), branché sur un
modèle Ollama **local**. Pas de site web, pas de plusieurs agents qui se
relaient : un modèle, une conversation par projet, et un bouton **🌐 Web** pour
activer une recherche web au coup par coup.

## Installation

Il faut [Node.js](https://nodejs.org) (18+) et [Ollama](https://ollama.com)
installés, avec un modèle téléchargé :

```bash
ollama pull qwen2.5:7b
```

Puis, dans le dossier du projet :

```bash
npm install
npm start
```

Au lancement, une **fenêtre de sélection de dossier** s'ouvre : choisis le
dossier du projet sur lequel tu veux travailler (ou annule pour reprendre le
dernier utilisé). Ollama doit tourner (`ollama serve`, ou il démarre tout seul
selon l'installation).

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
réponse. Le bouton se **désactive automatiquement** après l'envoi — il faut le
recliquer à chaque fois que tu veux une recherche pour un nouveau message.

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
| `ollama.js` | construction des messages + streaming de la réponse |
| `agent.js` | consigne système « outils » + extraction des appels d'outil |
| `tools.js` | lecture/écriture de fichiers confinée au dossier de projet |
| `search.js` | recherche web DuckDuckGo (requête + parsing) |
| `store.js` | réglages + historique, persistés en JSON |
| `renderer/index.html` | structure de la fenêtre |
| `renderer/renderer.js` | logique de l'interface (chat, outils, Web, réglages) |
| `renderer/style.css` | thème sombre |
| `selftest.js` | tests des modules purs, sans Electron ni réseau |

`ollama.js`, `search.js`, `store.js`, `tools.js` et `agent.js` ne dépendent pas
d'Electron : ils sont testables avec du Node pur.

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
