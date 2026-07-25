"use strict";

/**
 * Point d'entree Electron : choisit le dossier de projet au lancement,
 * cree la fenetre et relie l'IPC aux modules purs (store, ollama, search,
 * tools, agent). Toute la logique metier vit ailleurs ; ce fichier cable.
 */

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");

const store = require("./store");
const ollama = require("./ollama");
const search = require("./search");
const toolset = require("./tools");
const agent = require("./agent");

let mainWindow = null;
let inFlightController = null;
let currentProject = null;

function userDataDir() {
  return app.getPath("userData");
}

/** L'historique de chat vit DANS le dossier du projet, pas dans les donnees
 *  globales de l'appli : chaque projet garde sa propre conversation. */
function projectChatDir() {
  return path.join(currentProject, ".atelier-chat");
}

// --------------------------------------------------------------------------
// Choix du dossier de projet
// --------------------------------------------------------------------------

async function pickProjectFolder(defaultPath) {
  const res = await dialog.showOpenDialog({
    title: "Choisir le dossier du projet",
    defaultPath,
    buttonLabel: "Ouvrir ce projet",
    properties: ["openDirectory", "createDirectory"],
  });
  if (res.canceled || !res.filePaths.length) return null;
  return res.filePaths[0];
}

async function chooseProjectOnStartup() {
  // ATELIER_PROJECT permet de sauter le dialogue (tests automatises, scripts).
  if (process.env.ATELIER_PROJECT) {
    currentProject = process.env.ATELIER_PROJECT;
  } else {
    const globalSettings = store.loadSettings(userDataDir());
    const fallback = globalSettings.lastProject || path.join(os.homedir(), "AtelierProjects", "default");
    const picked = await pickProjectFolder(fallback);
    currentProject = picked || fallback;
  }
  fs.mkdirSync(currentProject, { recursive: true });
  store.saveSettings(userDataDir(), { lastProject: currentProject });
}

// --------------------------------------------------------------------------
// Fenetre
// --------------------------------------------------------------------------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 940,
    height: 720,
    minWidth: 480,
    minHeight: 480,
    backgroundColor: "#14110f",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(async () => {
  await chooseProjectOnStartup();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// --------------------------------------------------------------------------
// Projet, reglages, historique
// --------------------------------------------------------------------------

ipcMain.handle("project:get", () => currentProject);

ipcMain.handle("project:change", async () => {
  const picked = await pickProjectFolder(currentProject);
  if (!picked) return currentProject;
  currentProject = picked;
  fs.mkdirSync(currentProject, { recursive: true });
  store.saveSettings(userDataDir(), { lastProject: currentProject });
  return currentProject;
});

ipcMain.handle("settings:get", () => store.loadSettings(userDataDir()));
ipcMain.handle("settings:set", (_e, settings) => store.saveSettings(userDataDir(), settings));
ipcMain.handle("history:get", () => store.loadHistory(projectChatDir()));
ipcMain.handle("history:clear", () => {
  store.clearHistory(projectChatDir());
  return true;
});
ipcMain.handle("health:check", async () => {
  const settings = store.loadSettings(userDataDir());
  try {
    const { names, present } = await ollama.checkHealth(settings.ollamaUrl, settings.model);
    return { ok: true, present, model: settings.model, available: names };
  } catch (exc) {
    return { ok: false, error: String(exc.message || exc), model: settings.model };
  }
});

// --------------------------------------------------------------------------
// Chat : un seul modele, qui peut au besoin lire/ecrire dans le dossier du
// projet (boucle courte, pas d'etages d'agents). Le bouton Web ne vaut que
// pour ce message : le renderer le reinitialise a chaque envoi.
// --------------------------------------------------------------------------

ipcMain.on("chat:send", async (event, payload) => {
  const sender = event.sender;
  const question = ((payload && payload.text) || "").trim();
  const useWeb = !!(payload && payload.web);
  if (!question) return;

  const chatDir = projectChatDir();
  const settings = store.loadSettings(userDataDir());
  const history = store.loadHistory(chatDir);

  store.appendMessage(chatDir, { role: "user", content: question });

  let searchBlock = "";
  if (useWeb) {
    sender.send("chat:search", { status: "start", query: question });
    try {
      const results = await search.search(question);
      searchBlock = search.formatResults(question, results);
      sender.send("chat:search", { status: "done", query: question, results });
    } catch (exc) {
      sender.send("chat:search", { status: "error", message: String(exc.message || exc) });
    }
  }

  const sys = agent.systemPrompt(currentProject);
  let turnMessages = ollama.buildMessages(history, question, searchBlock, sys);

  inFlightController = new AbortController();
  let lastReply = "";
  try {
    for (let step = 1; step <= agent.MAX_STEPS; step++) {
      let reply = "";
      lastReply = await ollama.streamChat({
        url: settings.ollamaUrl,
        model: settings.model,
        messages: turnMessages,
        signal: inFlightController.signal,
        onToken: (piece) => {
          reply += piece;
          sender.send("chat:token", piece);
        },
      });

      const call = agent.extractToolCall(lastReply);
      if (!call) break; // reponse normale, rien a executer : c'est la reponse finale

      sender.send("chat:tool_call", { tool: call.tool, args: call.args, step });
      const result = toolset.execute(currentProject, call.tool, call.args);
      const observation = agent.formatObservation(call.tool, result);
      sender.send("chat:tool_result", { tool: call.tool, ok: result.ok, observation: observation.slice(0, 1500) });

      turnMessages = [
        ...turnMessages,
        { role: "assistant", content: lastReply },
        { role: "user", content: `[Resultat de ${call.tool}]\n${observation}` },
      ];
      sender.send("chat:step_boundary"); // le renderer ouvre une nouvelle bulle pour la suite
    }

    store.appendMessage(chatDir, { role: "assistant", content: lastReply });
    sender.send("chat:done", lastReply);
  } catch (exc) {
    if (exc.name === "AbortError") {
      if (lastReply) store.appendMessage(chatDir, { role: "assistant", content: lastReply });
      sender.send("chat:done", lastReply);
    } else {
      sender.send("chat:error", String(exc.message || exc));
    }
  } finally {
    inFlightController = null;
  }
});

ipcMain.on("chat:stop", () => {
  if (inFlightController) inFlightController.abort();
});
