"use strict";

/**
 * Point d'entree Electron : cree la fenetre et relie l'IPC aux modules
 * purs (store, ollama, search). Toute la logique metier vit ailleurs ;
 * ce fichier ne fait que le cablage.
 */

const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");

const store = require("./store");
const ollama = require("./ollama");
const search = require("./search");

let mainWindow = null;
let inFlightController = null;

function baseDir() {
  return app.getPath("userData");
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
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

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// --------------------------------------------------------------------------
// Reglages & historique
// --------------------------------------------------------------------------

ipcMain.handle("settings:get", () => store.loadSettings(baseDir()));
ipcMain.handle("settings:set", (_e, settings) => store.saveSettings(baseDir(), settings));
ipcMain.handle("history:get", () => store.loadHistory(baseDir()));
ipcMain.handle("history:clear", () => {
  store.clearHistory(baseDir());
  return true;
});
ipcMain.handle("health:check", async () => {
  const settings = store.loadSettings(baseDir());
  try {
    const { names, present } = await ollama.checkHealth(settings.ollamaUrl, settings.model);
    return { ok: true, present, model: settings.model, available: names };
  } catch (exc) {
    return { ok: false, error: String(exc.message || exc), model: settings.model };
  }
});

// --------------------------------------------------------------------------
// Chat : le bouton « Web » ne vaut que pour CE message (le renderer le
// reinitialise a chaque envoi, il n'est jamais transmis comme etat persistant)
// --------------------------------------------------------------------------

ipcMain.on("chat:send", async (event, payload) => {
  const sender = event.sender;
  const question = ((payload && payload.text) || "").trim();
  const useWeb = !!(payload && payload.web);
  if (!question) return;

  const dir = baseDir();
  const settings = store.loadSettings(dir);
  const history = store.loadHistory(dir);

  store.appendMessage(dir, { role: "user", content: question });

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

  const messages = ollama.buildMessages(history, question, searchBlock);

  inFlightController = new AbortController();
  let full = "";
  try {
    full = await ollama.streamChat({
      url: settings.ollamaUrl,
      model: settings.model,
      messages,
      signal: inFlightController.signal,
      onToken: (piece) => sender.send("chat:token", piece),
    });
    store.appendMessage(dir, { role: "assistant", content: full });
    sender.send("chat:done", full);
  } catch (exc) {
    if (exc.name === "AbortError") {
      if (full) store.appendMessage(dir, { role: "assistant", content: full });
      sender.send("chat:done", full);
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
