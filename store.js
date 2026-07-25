"use strict";

/**
 * Persistance locale : reglages et historique de conversation.
 *
 * Prend toujours `baseDir` en parametre plutot que d'appeler Electron
 * directement, pour rester testable avec du Node pur (voir selftest.js).
 * C'est main.js qui fournit app.getPath('userData').
 */

const fs = require("fs");
const path = require("path");

const DEFAULT_SETTINGS = {
  ollamaUrl: "http://localhost:11434",
  model: "qwen2.5:7b",
};

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function settingsPath(baseDir) {
  return path.join(baseDir, "settings.json");
}

function historyPath(baseDir) {
  return path.join(baseDir, "history.json");
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJsonAtomic(file, data) {
  ensureDir(path.dirname(file));
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf8");
  fs.renameSync(tmp, file);
}

function loadSettings(baseDir) {
  return { ...DEFAULT_SETTINGS, ...readJson(settingsPath(baseDir), {}) };
}

function saveSettings(baseDir, settings) {
  const merged = { ...loadSettings(baseDir), ...(settings || {}) };
  writeJsonAtomic(settingsPath(baseDir), merged);
  return merged;
}

function loadHistory(baseDir) {
  return readJson(historyPath(baseDir), { messages: [] }).messages || [];
}

function appendMessage(baseDir, message) {
  const messages = loadHistory(baseDir);
  messages.push({ ts: Date.now(), ...message });
  writeJsonAtomic(historyPath(baseDir), { messages });
  return messages;
}

function clearHistory(baseDir) {
  writeJsonAtomic(historyPath(baseDir), { messages: [] });
}

module.exports = {
  DEFAULT_SETTINGS,
  loadSettings,
  saveSettings,
  loadHistory,
  appendMessage,
  clearHistory,
};
