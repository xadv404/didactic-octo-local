"use strict";

/**
 * Pont securise entre le renderer (sandboxe, sans Node) et le processus
 * principal. N'expose que des fonctions precises, jamais ipcRenderer brut.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("atelier", {
  sendMessage: (payload) => ipcRenderer.send("chat:send", payload),
  stop: () => ipcRenderer.send("chat:stop"),

  onToken: (cb) => ipcRenderer.on("chat:token", (_e, text) => cb(text)),
  onDone: (cb) => ipcRenderer.on("chat:done", (_e, full) => cb(full)),
  onError: (cb) => ipcRenderer.on("chat:error", (_e, message) => cb(message)),
  onSearch: (cb) => ipcRenderer.on("chat:search", (_e, info) => cb(info)),
  onToolCall: (cb) => ipcRenderer.on("chat:tool_call", (_e, info) => cb(info)),
  onToolResult: (cb) => ipcRenderer.on("chat:tool_result", (_e, info) => cb(info)),
  onStepBoundary: (cb) => ipcRenderer.on("chat:step_boundary", () => cb()),

  getHistory: () => ipcRenderer.invoke("history:get"),
  clearHistory: () => ipcRenderer.invoke("history:clear"),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (s) => ipcRenderer.invoke("settings:set", s),
  checkHealth: () => ipcRenderer.invoke("health:check"),

  getProject: () => ipcRenderer.invoke("project:get"),
  changeProject: () => ipcRenderer.invoke("project:change"),
});
