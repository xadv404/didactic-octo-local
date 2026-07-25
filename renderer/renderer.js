"use strict";

const feed = document.getElementById("feed");
let intro = document.getElementById("intro");
const qEl = document.getElementById("q");
const goBtn = document.getElementById("go");
const webToggle = document.getElementById("webToggle");
const webAlways = document.getElementById("webAlways");
const dot = document.getElementById("dot");
const statusTxt = document.getElementById("statusTxt");

let webOn = false;
let webAlwaysOn = false;
let busy = false;
let liveEl = null;
let liveRaw = "";
let lastTrace = null;

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : s;
  return d.innerHTML;
}

function fmt(raw) {
  const parts = (raw || "").split("```");
  let html = "";
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf("\n");
      const code = nl >= 0 ? part.slice(nl + 1) : part;
      html += `<pre>${esc(code)}</pre>`;
    } else {
      html += esc(part)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\n/g, "<br>");
    }
  });
  return html;
}

function scrollDown() {
  feed.scrollTop = feed.scrollHeight;
}

function removeIntro() {
  if (intro) {
    intro.remove();
    intro = null;
  }
}

function addMessage(role, content) {
  removeIntro();
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="tag">${role === "user" ? "Toi" : "Assistant"}</div>${fmt(content)}`;
  feed.appendChild(el);
  scrollDown();
  return el;
}

function addSearchTrace(query) {
  removeIntro();
  const el = document.createElement("div");
  el.className = "searchtrace";
  el.innerHTML = `<div>🌐 Recherche : ${esc(query)}…</div>`;
  feed.appendChild(el);
  scrollDown();
  return el;
}

function addToolTrace() {
  removeIntro();
  const el = document.createElement("div");
  el.className = "tooltrace";
  feed.appendChild(el);
  scrollDown();
  return el;
}

function setBusy(state) {
  busy = state;
  goBtn.disabled = state;
  goBtn.textContent = state ? "En cours…" : "Envoyer";
}

function setWebToggle(on) {
  webOn = on;
  webToggle.classList.toggle("on", on);
}

/** Envoie le message courant. Par defaut, le bouton Web se reinitialise
 *  apres l'envoi (il ne vaut que pour ce message) — sauf si « Toujours »
 *  est coche, auquel cas il reste actif pour tous les messages suivants. */
function send() {
  const text = qEl.value.trim();
  if (!text || busy) return;

  addMessage("user", text);
  qEl.value = "";
  qEl.style.height = "auto";
  setBusy(true);

  const useWeb = webOn;
  if (!webAlwaysOn) setWebToggle(false);
  if (useWeb) addSearchTrace(text);

  liveEl = null;
  liveRaw = "";

  window.atelier.sendMessage({ text, web: useWeb });
}

webToggle.addEventListener("click", () => {
  if (webAlwaysOn) return; // pilote par la case "Toujours" tant qu'elle est cochee
  setWebToggle(!webOn);
});

webAlways.addEventListener("change", () => {
  webAlwaysOn = webAlways.checked;
  webToggle.disabled = webAlwaysOn;
  setWebToggle(webAlwaysOn);
});
goBtn.addEventListener("click", send);
qEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
qEl.addEventListener("input", () => {
  qEl.style.height = "auto";
  qEl.style.height = Math.min(qEl.scrollHeight, 160) + "px";
});

// --------------------------------------------------------------------------
// Evenements en provenance du processus principal
// --------------------------------------------------------------------------

window.atelier.onSearch((info) => {
  const el = feed.querySelector(".searchtrace:last-of-type");
  if (!el) return;
  if (info.status === "done") {
    const rows = (info.results || [])
      .map(
        (r, i) =>
          `<div class="hit">[${i + 1}] <a href="${esc(r.url)}" target="_blank">${esc(r.title)}</a><br>${esc(
            (r.snippet || "").slice(0, 160)
          )}</div>`
      )
      .join("");
    el.innerHTML = `<div>🌐 Résultats pour « ${esc(info.query)} »</div>${rows || '<div class="hit">(rien trouvé)</div>'}`;
  } else if (info.status === "error") {
    el.innerHTML += `<div class="hit">Échec de la recherche : ${esc(info.message)}</div>`;
  }
  scrollDown();
});

window.atelier.onToken((text) => {
  if (!liveEl) liveEl = addMessage("assistant", "");
  liveRaw += text;
  liveEl.innerHTML = `<div class="tag">Assistant</div>${fmt(liveRaw)}`;
  liveEl.classList.add("caret");
  scrollDown();
});

window.atelier.onToolCall((info) => {
  const el = addToolTrace();
  let argstr = "";
  try {
    argstr = JSON.stringify(info.args);
  } catch {
    /* ignore */
  }
  el.innerHTML =
    `<div class="tcall">🔧 <span class="tn">${esc(info.tool)}</span></div>` +
    (argstr && argstr !== "{}" ? `<div class="targs">${esc(argstr)}</div>` : "") +
    `<div class="tout" style="display:none"></div>`;
  lastTrace = el;
  scrollDown();
});

window.atelier.onToolResult((info) => {
  if (!lastTrace) return;
  const out = lastTrace.querySelector(".tout");
  out.style.display = "block";
  out.className = "tout" + (info.ok ? "" : " err");
  out.textContent = info.observation || "";
  scrollDown();
});

window.atelier.onStepBoundary(() => {
  // Le modele va reprendre apres le resultat d'un outil : on ferme la bulle
  // en cours, la suite s'affichera dans une nouvelle bulle "Assistant".
  if (liveEl) liveEl.classList.remove("caret");
  liveEl = null;
  liveRaw = "";
});

window.atelier.onDone(() => {
  if (liveEl) liveEl.classList.remove("caret");
  liveEl = null;
  liveRaw = "";
  lastTrace = null;
  setBusy(false);
  qEl.focus();
});

window.atelier.onError((message) => {
  if (!liveEl) liveEl = addMessage("assistant", "");
  liveEl.classList.remove("caret");
  liveRaw += `\n\n[Erreur : ${message}]`;
  liveEl.innerHTML = `<div class="tag">Assistant</div>${fmt(liveRaw)}`;
  liveEl = null;
  liveRaw = "";
  setBusy(false);
});

// --------------------------------------------------------------------------
// Sante, historique, reglages
// --------------------------------------------------------------------------

async function refreshHealth() {
  try {
    const h = await window.atelier.checkHealth();
    if (h.ok && h.present) {
      dot.className = "dot ok";
      statusTxt.textContent = `Prêt · ${h.model}`;
    } else if (h.ok) {
      dot.className = "dot no";
      statusTxt.textContent = `Modèle absent — ollama pull ${h.model}`;
    } else {
      dot.className = "dot no";
      statusTxt.textContent = "Ollama hors ligne";
    }
  } catch {
    dot.className = "dot no";
    statusTxt.textContent = "Ollama hors ligne";
  }
}

async function loadHistory() {
  const messages = await window.atelier.getHistory();
  if (messages.length) removeIntro();
  for (const m of messages) addMessage(m.role, m.content);
}

function shortenPath(p) {
  if (!p) return "…";
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : p;
}

async function loadProject() {
  const p = await window.atelier.getProject();
  document.getElementById("projectName").textContent = shortenPath(p);
  document.getElementById("projectBtn").title = p ? `${p}\n(cliquer pour changer)` : "Changer de dossier";
}

document.getElementById("projectBtn").addEventListener("click", async () => {
  await window.atelier.changeProject();
  location.reload();
});

const settingsModal = document.getElementById("settingsModal");
document.getElementById("settingsBtn").addEventListener("click", async () => {
  const s = await window.atelier.getSettings();
  document.getElementById("stUrl").value = s.ollamaUrl;
  document.getElementById("stModel").value = s.model;
  settingsModal.classList.add("on");
});
document.getElementById("stCancel").addEventListener("click", () => settingsModal.classList.remove("on"));
document.getElementById("stSave").addEventListener("click", async () => {
  await window.atelier.setSettings({
    ollamaUrl: document.getElementById("stUrl").value.trim() || "http://localhost:11434",
    model: document.getElementById("stModel").value.trim() || "qwen2.5:7b",
  });
  settingsModal.classList.remove("on");
  refreshHealth();
});
settingsModal.addEventListener("click", (e) => {
  if (e.target === settingsModal) settingsModal.classList.remove("on");
});

document.getElementById("clearBtn").addEventListener("click", async () => {
  if (!confirm("Effacer toute la conversation ?")) return;
  await window.atelier.clearHistory();
  location.reload();
});

loadProject();
loadHistory();
refreshHealth();
setInterval(refreshHealth, 20000);
