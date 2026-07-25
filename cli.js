#!/usr/bin/env node
"use strict";

/**
 * Atelier en ligne de commande : meme moteur que l'app Electron (un seul
 * modele Ollama, outils fichier confines au dossier de projet, recherche web
 * au coup par coup), sans interface graphique. Reutilise les memes modules
 * purs et le meme format d'historique (<projet>/.atelier-chat/) : un projet
 * ouvert en CLI garde sa conversation si on le rouvre plus tard dans l'app.
 *
 * Usage :
 *   atelier [dossier] [--model <nom>] [--url <adresse>]
 *   node cli.js .
 */

const readline = require("readline");
const path = require("path");
const os = require("os");
const fs = require("fs");

const store = require("./store");
const ollama = require("./ollama");
const search = require("./search");
const tools = require("./tools");
const agent = require("./agent");

const GLOBAL_DIR = path.join(os.homedir(), ".atelier-cli");

/** Fonction pure : lit les arguments de la ligne de commande. */
function parseArgs(argv) {
  const args = { folder: null, model: null, url: null, help: false };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--model") args.model = argv[++i];
    else if (a === "--url") args.url = argv[++i];
    else if (a === "--help" || a === "-h") args.help = true;
    else rest.push(a);
  }
  args.folder = rest[0] || process.cwd();
  return args;
}

function printHelp() {
  console.log(
    [
      "",
      "Atelier — chatbot en ligne de commande sur un modele Ollama local.",
      "",
      "Usage :",
      "  atelier [dossier] [--model <nom>] [--url <adresse>]",
      "",
      "  dossier   Dossier de projet (lecture/ecriture de fichiers).",
      "            Par defaut : dossier courant.",
      "  --model   Modele Ollama a utiliser (ex. qwen2.5:7b). Memorise pour la prochaine fois.",
      "  --url     Adresse d'Ollama (defaut http://localhost:11434). Memorisee aussi.",
      "",
      "Dans le chat :",
      "  /web <message>   Declenche une recherche web pour CE message uniquement.",
      "  /web on          Active la recherche web pour TOUS les messages suivants.",
      "  /web off         Revient au mode message par message (defaut).",
      "  /clear           Efface l'historique de ce projet.",
      "  /help            Affiche cette aide.",
      "  /exit ou /quit   Quitte (Ctrl+D aussi).",
      "",
    ].join("\n")
  );
}

/**
 * Fonction pure : interprete une ligne de chat selon l'etat "toujours" en
 * cours. Renvoie soit une bascule de mode ({ setAlways }), soit un message
 * a traiter ({ useWeb, question }).
 */
function interpretWebCommand(raw, alwaysWeb) {
  if (raw === "/web on") return { setAlways: true };
  if (raw === "/web off") return { setAlways: false };
  const oneShot = raw.startsWith("/web ");
  const question = oneShot ? raw.slice(5).trim() : raw;
  return { useWeb: alwaysWeb || oneShot, question };
}

async function runTurn({ projectRoot, chatDir, settings, question, useWeb }) {
  const history = store.loadHistory(chatDir);
  store.appendMessage(chatDir, { role: "user", content: question });

  let searchBlock = "";
  if (useWeb) {
    process.stdout.write("🌐 Recherche…\n");
    try {
      const results = await search.search(question);
      searchBlock = search.formatResults(question, results);
      results.forEach((r, i) => console.log(`  [${i + 1}] ${r.title}\n      ${r.url}`));
      if (!results.length) console.log("  (rien trouve)");
    } catch (exc) {
      console.log(`  Echec de la recherche : ${exc.message}`);
    }
    console.log("");
  }

  const sys = agent.systemPrompt(projectRoot);
  let turnMessages = ollama.buildMessages(history, question, searchBlock, sys);
  let lastReply = "";

  for (let step = 1; step <= agent.MAX_STEPS; step++) {
    lastReply = await ollama.streamChat({
      url: settings.ollamaUrl,
      model: settings.model,
      messages: turnMessages,
      onToken: (piece) => process.stdout.write(piece),
    });
    process.stdout.write("\n");

    const call = agent.extractToolCall(lastReply);
    if (!call) break; // reponse normale : c'est la reponse finale de ce tour

    console.log(`\n🔧 ${call.tool}(${JSON.stringify(call.args)})`);
    const result = tools.execute(projectRoot, call.tool, call.args);
    const observation = agent.formatObservation(call.tool, result);
    console.log(observation.slice(0, 800));
    console.log("");

    turnMessages = [
      ...turnMessages,
      { role: "assistant", content: lastReply },
      { role: "user", content: `[Resultat de ${call.tool}]\n${observation}` },
    ];
  }

  store.appendMessage(chatDir, { role: "assistant", content: lastReply });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const projectRoot = path.resolve(args.folder);
  fs.mkdirSync(projectRoot, { recursive: true });
  const chatDir = path.join(projectRoot, ".atelier-chat");

  let settings = store.loadSettings(GLOBAL_DIR);
  if (args.model || args.url) {
    settings = store.saveSettings(GLOBAL_DIR, {
      ...(args.model ? { model: args.model } : {}),
      ...(args.url ? { ollamaUrl: args.url } : {}),
    });
  }

  console.log(`Atelier — ${projectRoot}`);
  console.log(`Modele : ${settings.model}  ·  Ollama : ${settings.ollamaUrl}`);
  try {
    const health = await ollama.checkHealth(settings.ollamaUrl, settings.model);
    if (!health.present) console.log(`⚠ Modele absent — essaie : ollama pull ${settings.model}`);
  } catch {
    console.log("⚠ Ollama injoignable — verifie qu'il tourne (ollama serve).");
  }
  console.log("Tape /help pour les commandes, /exit pour quitter.\n");

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: "> " });
  rl.prompt();

  // File d'attente : traite une ligne a la fois, meme si plusieurs arrivent
  // avant qu'un tour ait fini (collage multi-lignes, frappe rapide) — sans
  // ca, deux tours pourraient s'executer en parallele et corrompre
  // l'historique (lectures/ecritures concurrentes du meme fichier JSON).
  const pending = [];
  let draining = false;
  let closing = false;
  let currentDrain = null;
  let alwaysWeb = false;

  async function processLine(raw) {
    if (!raw) return;
    if (raw === "/exit" || raw === "/quit") {
      closing = true;
      rl.close();
      return;
    }
    if (raw === "/help") {
      printHelp();
      return;
    }
    if (raw === "/clear") {
      store.clearHistory(chatDir);
      console.log("Historique efface.\n");
      return;
    }

    const interpreted = interpretWebCommand(raw, alwaysWeb);
    if ("setAlways" in interpreted) {
      alwaysWeb = interpreted.setAlways;
      console.log(
        alwaysWeb
          ? "🌐 Recherche web activee pour tous les messages (jusqu'a /web off).\n"
          : "Recherche web desactivee par defaut (utilise /web <message> au coup par coup).\n"
      );
      return;
    }
    const { useWeb, question } = interpreted;
    if (!question) return;

    try {
      await runTurn({ projectRoot, chatDir, settings, question, useWeb });
    } catch (exc) {
      console.log(`\n[Erreur : ${exc.message}]`);
    }
    console.log("");
  }

  async function drain() {
    if (draining) return;
    draining = true;
    while (pending.length) {
      await processLine(pending.shift());
    }
    draining = false;
    if (!closing) rl.prompt();
  }

  /** Lance drain() si besoin et garde une reference au tour en cours, pour
   *  que 'close' (EOF, Ctrl+D) puisse l'attendre avant de quitter le process
   *  — sinon une reponse en train d'arriver serait coupee net. */
  function kickDrain() {
    if (!currentDrain) {
      currentDrain = drain().finally(() => {
        currentDrain = null;
      });
    }
    return currentDrain;
  }

  rl.on("line", (line) => {
    pending.push(line.trim());
    kickDrain();
  });

  rl.on("close", async () => {
    if (currentDrain) await currentDrain;
    console.log("\nÀ bientôt.");
    process.exit(0);
  });
}

module.exports = { parseArgs, interpretWebCommand };

if (require.main === module) {
  main();
}
