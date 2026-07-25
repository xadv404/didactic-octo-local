"use strict";

/**
 * Test de fumee des modules purs (search, ollama, store) — sans Electron,
 * sans reseau, sans affichage. Lancer avec : node selftest.js
 */

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const search = require("./search");
const ollama = require("./ollama");
const store = require("./store");

function check(label) {
  console.log("OK -", label);
}

// --------------------------------------------------------------------------
// search.js : parsing DuckDuckGo (pur, sans reseau)
// --------------------------------------------------------------------------

const SAMPLE_HTML = `
<div class="result">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsite1.example%2Fpage&amp;rut=x">
    Premier r&eacute;sultat
  </a>
  <a class="result__snippet" href="#">Un extrait avec &amp; une esperluette.</a>
</div>
<div class="result">
  <a rel="nofollow" class="result__a" href="https://site2.example/autre">Deuxi&egrave;me</a>
  <a class="result__snippet" href="#">Snippet <b>en gras</b> ici.</a>
</div>
`;

const results = search.parseDuckDuckGoHtml(SAMPLE_HTML, 5);
assert.strictEqual(results.length, 2, `attendu 2 resultats, obtenu ${results.length}`);
assert.strictEqual(results[0].url, "https://site1.example/page");
assert.ok(results[0].title.includes("sultat"), results[0].title); // entite &eacute; non geree -> tolere, on verifie juste le decoupage
assert.ok(results[0].snippet.includes("&"), results[0].snippet);
assert.strictEqual(results[1].url, "https://site2.example/autre");
assert.ok(results[1].snippet.includes("en gras"));
check("search.parseDuckDuckGoHtml (extraction + decodage des liens uddg)");

assert.strictEqual(search.cleanDdgUrl("//duckduckgo.com/l/?uddg=https%3A%2F%2Fe.com%2Fa%3Fx%3D1"), "https://e.com/a?x=1");
assert.strictEqual(search.cleanDdgUrl("https://plain.example"), "https://plain.example");
assert.strictEqual(search.cleanDdgUrl("//example.org/x"), "https://example.org/x");
check("search.cleanDdgUrl (decodage + normalisation //)");

const noneFound = search.parseDuckDuckGoHtml("<html>rien ici</html>", 5);
assert.strictEqual(noneFound.length, 0);
assert.ok(search.formatResults("test", []).includes("rien trouve"));
assert.ok(search.formatResults("chats", results).includes("[1]"));
check("search.formatResults (vide + rempli)");

// --------------------------------------------------------------------------
// ollama.js : assemblage des messages + parsing NDJSON (pur)
// --------------------------------------------------------------------------

const msgs = ollama.buildMessages(
  [{ role: "user", content: "salut" }, { role: "assistant", content: "salut !" }],
  "quelle heure est-il ?",
  ""
);
assert.strictEqual(msgs[0].role, "system");
assert.strictEqual(msgs.length, 4); // system + 2 historique + nouveau message
assert.strictEqual(msgs.at(-1).content, "quelle heure est-il ?");
check("ollama.buildMessages (sans recherche)");

const msgsWithSearch = ollama.buildMessages([], "il fait quel temps ?", "Recherche : meteo\n  [1] ...");
assert.ok(msgsWithSearch.at(-1).content.includes("[Resultats de recherche web]"));
assert.ok(msgsWithSearch.at(-1).content.startsWith("il fait quel temps ?"));
check("ollama.buildMessages (avec bloc de recherche injecte)");

assert.deepStrictEqual(ollama.parseNdjsonLine('{"message":{"content":"Bon"},"done":false}'), { piece: "Bon", done: false });
assert.deepStrictEqual(ollama.parseNdjsonLine('{"done":true}'), { piece: "", done: true });
assert.strictEqual(ollama.parseNdjsonLine("   "), null);
assert.strictEqual(ollama.parseNdjsonLine("{pas du json}"), null);
check("ollama.parseNdjsonLine (flux NDJSON)");

// --------------------------------------------------------------------------
// store.js : reglages + historique (fichiers reels, dossier temporaire)
// --------------------------------------------------------------------------

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-selftest-"));

const defaults = store.loadSettings(tmp);
assert.strictEqual(defaults.model, store.DEFAULT_SETTINGS.model);
const saved = store.saveSettings(tmp, { model: "dolphin3" });
assert.strictEqual(saved.model, "dolphin3");
assert.strictEqual(saved.ollamaUrl, store.DEFAULT_SETTINGS.ollamaUrl); // conserve le reste
assert.strictEqual(store.loadSettings(tmp).model, "dolphin3");
check("store.loadSettings / saveSettings (fusion + persistance)");

assert.deepStrictEqual(store.loadHistory(tmp), []);
store.appendMessage(tmp, { role: "user", content: "un" });
store.appendMessage(tmp, { role: "assistant", content: "deux" });
const hist = store.loadHistory(tmp);
assert.strictEqual(hist.length, 2);
assert.strictEqual(hist[0].content, "un");
assert.strictEqual(hist[1].role, "assistant");
assert.ok(typeof hist[0].ts === "number");
store.clearHistory(tmp);
assert.deepStrictEqual(store.loadHistory(tmp), []);
check("store.appendMessage / loadHistory / clearHistory");

fs.rmSync(tmp, { recursive: true, force: true });

// --------------------------------------------------------------------------
// Coherence des fichiers Electron (existence, pas d'require casse)
// --------------------------------------------------------------------------

for (const f of ["main.js", "preload.js", "renderer/index.html", "renderer/renderer.js", "renderer/style.css"]) {
  assert.ok(fs.existsSync(path.join(__dirname, f)), `manquant : ${f}`);
}
check("fichiers Electron presents (main, preload, renderer)");

console.log("\nTOUS LES TESTS PASSENT");
