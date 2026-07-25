# Atelier — chatbot de bureau (Electron)

Un chatbot **simple** en application de bureau (Electron), branché sur un
modele Ollama **local**. Pas de site web, pas de plusieurs agents qui se
relaient : un modele, une conversation, et un bouton **🌐 Web** pour activer
une recherche web au coup par coup.

## Installation

Il faut [Node.js](https://nodejs.org) (18+) et [Ollama](https://ollama.com)
installes, avec un modele telecharge :

```bash
ollama pull qwen2.5:7b
```

Puis, dans le dossier du projet :

```bash
npm install
npm start
```

La fenetre s'ouvre directement. Ollama doit tourner (`ollama serve`, ou il
demarre tout seul selon l'installation).

## Le bouton Web

À côté de la zone de saisie, le bouton **🌐 Web** n'agit **que pour le message
en cours** : s'il est actif quand tu appuies sur Envoyer, ce message declenche
une recherche DuckDuckGo dont les resultats sont injectes au modele avant sa
reponse. Le bouton se **desactive automatiquement** apres l'envoi — il faut le
recliquer a chaque fois que tu veux une recherche pour un nouveau message.

Sans clic sur Web : conversation normale, aucun acces reseau autre qu'Ollama.

## Reglages

L'icone ⚙ (en haut) ouvre un panneau pour changer :

- **Adresse Ollama** — `http://localhost:11434` par defaut. Peut pointer vers
  un Ollama distant (ex. un VPS) en mettant son IP.
- **Modele** — le nom exact tel qu'il apparait dans `ollama list` (ex.
  `qwen2.5:7b`, `qwen2.5-coder:7b`, `dolphin3` pour un modele moins censure).

La pastille en haut a gauche indique si Ollama est joignable et si le modele
choisi est bien installe.

## Historique

La conversation est sauvegardee automatiquement sur le disque (dossier de
donnees de l'application) et rechargee a l'ouverture. Le bouton 🗑 efface tout.

## Architecture (fichiers courts)

| Fichier | Rôle |
|---|---|
| `main.js` | processus principal Electron : fenêtre + câblage IPC |
| `preload.js` | pont sécurisé entre la fenêtre et `main.js` |
| `ollama.js` | construction des messages + streaming de la réponse |
| `search.js` | recherche web DuckDuckGo (requête + parsing) |
| `store.js` | réglages + historique, persistés en JSON |
| `renderer/index.html` | structure de la fenêtre |
| `renderer/renderer.js` | logique de l'interface (chat, bouton Web, réglages) |
| `renderer/style.css` | thème sombre |
| `selftest.js` | tests des modules purs, sans Electron ni réseau |

`ollama.js`, `search.js` et `store.js` ne dépendent pas d'Electron : ils sont
testables avec du Node pur.

```bash
npm test          # ou : node selftest.js
```

## Sécurité

La fenêtre tourne avec `contextIsolation` et `sandbox` activés, sans accès
Node direct au contenu web — seules les fonctions explicitement exposées dans
`preload.js` sont disponibles côté interface.

## Diagnostic

| Symptôme | Cause |
|---|---|
| Pastille rouge, « Ollama hors ligne » | `ollama serve` n'est pas lancé, ou mauvaise adresse dans les réglages |
| « Modèle absent » | Le nom ne correspond à rien d'installé — vérifie avec `ollama list` |
| Recherche en échec | DuckDuckGo peut bloquer certaines IP (rare sur un poste résidentiel) |
| Rien ne se passe au clic sur Web | Le bouton ne vaut que pour le *prochain* envoi — il faut cliquer juste avant Envoyer |
