"use strict";

/**
 * Boucle d'un seul modele qui peut, au besoin, lire/ecrire des fichiers du
 * projet. Pas d'etages d'agents : le meme modele reflechit et agit, un outil
 * a la fois, jusqu'a ce qu'il reponde normalement (sans bloc JSON) ou que
 * MAX_STEPS soit atteint.
 */

const tools = require("./tools");

const MAX_STEPS = 8;

function systemPrompt(projectRoot) {
  return (
    "Tu es un assistant de bureau. Tu peux discuter normalement, et tu as " +
    `acces en lecture/ecriture au dossier de projet suivant :\n${projectRoot}\n\n` +
    "Pour agir sur un fichier, termine ta reponse par UN SEUL bloc JSON :\n" +
    "```json\n" +
    '{"tool": "nom_outil", "args": { ... }}\n' +
    "```\n\n" +
    "Outils disponibles :\n" +
    tools.toolsManual() +
    "\n\n" +
    "Regles :\n" +
    "- N'utilise un outil QUE si c'est necessaire pour repondre (lire un fichier existant, " +
    "en creer ou en modifier un). Pour une question normale, reponds directement, sans bloc JSON.\n" +
    "- N'utilise JAMAIS un nom d'outil hors de cette liste (pas de recherche web, pas de shell : " +
    "tu ne les as pas). Si tu n'as pas d'outil adapte, dis-le et reponds avec tes connaissances.\n" +
    "- Un seul outil par tour ; attends le resultat avant d'en appeler un autre.\n" +
    "- Les chemins sont relatifs a la racine du projet.\n" +
    "- N'invente jamais le contenu d'un fichier que tu n'as pas lu, ni le resultat d'un outil."
  );
}

const JSON_BLOCK = /```(?:json)?\s*(\{[\s\S]*?\})\s*```/g;

/** Fonction pure : trouve le dernier bloc {tool, args} dans une reponse.
 *  N'accepte que les outils reellement disponibles (tools.TOOLS) : un modele
 *  peut halluciner un outil qui n'existe pas (ex. "web_search", qu'il connait
 *  d'entrainements generaux mais qui n'est pas cable ici) — dans ce cas on
 *  l'ignore et la reponse est traitee comme un texte normal, sans l'executer
 *  ni afficher de faux essai d'outil dans l'interface. */
function extractToolCall(text) {
  const matches = [...(text || "").matchAll(JSON_BLOCK)];
  for (let i = matches.length - 1; i >= 0; i--) {
    let obj;
    try {
      obj = JSON.parse(matches[i][1]);
    } catch {
      continue;
    }
    if (obj && typeof obj === "object" && typeof obj.tool === "string" && tools.TOOLS[obj.tool]) {
      const args = obj.args && typeof obj.args === "object" ? obj.args : {};
      return { tool: obj.tool, args };
    }
  }
  return null;
}

function formatObservation(name, result) {
  if (!result.ok) return `ECHEC : ${result.error || "erreur inconnue"}`;
  if (name === "read_file") return `${result.path} (${result.lines} lignes) :\n${result.content}`;
  if (name === "list_dir") {
    const rows = result.entries.map((e) => `${e.name}${e.type === "dir" ? "/" : ""}`);
    return `${result.path} :\n` + (rows.length ? rows.join("\n") : "(vide)");
  }
  return JSON.stringify(result);
}

module.exports = { systemPrompt, extractToolCall, formatObservation, MAX_STEPS };
