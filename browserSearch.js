"use strict";

/**
 * Recherche web via une fenetre Chromium cachee (headless) : Electron
 * embarque deja Chromium, on l'utilise directement plutot que de rejouer une
 * requete HTTP brute — plus proche d'un vrai navigateur (rendu reel, en-tetes
 * authentiques), donc plus resistant aux blocages anti-bot et aux changements
 * de mise en page que le simple parsing regex de search.js.
 *
 * Necessite Electron (BrowserWindow) : ne s'utilise que dans le processus
 * principal, jamais avec du Node nu (voir search.js pour la version testable
 * sans Electron, gardee comme repli).
 */

const { BrowserWindow } = require("electron");

const RESULT_LIMIT = 5;

// html.duckduckgo.com : resultats et extraits regroupes dans .result__body.
const EXTRACT_HTML_JS = `
(() => {
  const out = [];
  document.querySelectorAll('.result__body').forEach((block) => {
    if (out.length >= ${RESULT_LIMIT}) return;
    const a = block.querySelector('a.result__a');
    if (!a) return;
    const snippetEl = block.querySelector('.result__snippet');
    out.push({
      title: (a.textContent || '').trim(),
      snippet: (snippetEl ? snippetEl.textContent : '').trim(),
      url: a.href || '',
    });
  });
  return out;
})();
`;

// lite.duckduckgo.com : mise en page en table, liens et extraits separes.
const EXTRACT_LITE_JS = `
(() => {
  const out = [];
  const links = document.querySelectorAll('a.result-link');
  const snippets = document.querySelectorAll('.result-snippet');
  for (let i = 0; i < links.length && out.length < ${RESULT_LIMIT}; i++) {
    out.push({
      title: (links[i].textContent || '').trim(),
      snippet: (snippets[i] ? snippets[i].textContent : '').trim(),
      url: links[i].href || '',
    });
  }
  return out;
})();
`;

function loadWithTimeout(win, url, timeoutMs) {
  return new Promise((resolve, reject) => {
    let done = false;
    const finish = (fn, arg) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      fn(arg);
    };
    const timer = setTimeout(() => finish(reject, new Error("Delai de chargement depasse.")), timeoutMs);
    win.webContents.once("did-finish-load", () => finish(resolve));
    win.webContents.once("did-fail-load", (_e, code, desc) => {
      finish(reject, new Error(`Echec de chargement (${code} ${desc || ""})`.trim()));
    });
    win.loadURL(url).catch((exc) => finish(reject, exc));
  });
}

/** Recherche via Chromium headless. Renvoie [] si rien de trouve, plutot
 *  que d'echouer, pour laisser l'appelant decider d'un repli eventuel. */
async function searchWithChromium(query, { timeoutMs = 20000 } = {}) {
  const win = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, images: false },
  });
  try {
    const htmlUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
    await loadWithTimeout(win, htmlUrl, timeoutMs);
    const first = await win.webContents.executeJavaScript(EXTRACT_HTML_JS);
    if (Array.isArray(first) && first.length) return first;

    const liteUrl = `https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}`;
    await loadWithTimeout(win, liteUrl, timeoutMs);
    const second = await win.webContents.executeJavaScript(EXTRACT_LITE_JS);
    return Array.isArray(second) ? second : [];
  } finally {
    win.destroy();
  }
}

module.exports = { searchWithChromium };
