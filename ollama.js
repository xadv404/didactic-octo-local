"use strict";

/**
 * Acces au modele Ollama : construction des messages et streaming de la
 * reponse via /api/chat. Le decoupage du corps NDJSON est isole dans
 * parseNdjsonLine pour rester testable sans reseau.
 */

const DEFAULT_SYSTEM =
  "Tu es un assistant utile, direct et concis. Reponds en francais sauf si on " +
  "te parle dans une autre langue. Si des resultats de recherche web sont " +
  "fournis, appuie-toi dessus et cite les sources par leur URL ; s'ils ne " +
  "repondent pas a la question, dis-le clairement plutot que d'inventer.";

/** Fonction pure : assemble l'historique + le nouveau message (+ recherche). */
function buildMessages(history, userText, searchBlock) {
  const messages = [{ role: "system", content: DEFAULT_SYSTEM }];
  for (const m of history || []) {
    if (m && m.role && m.content) messages.push({ role: m.role, content: m.content });
  }
  let content = userText;
  if (searchBlock) {
    content =
      `${userText}\n\n[Resultats de recherche web]\n${searchBlock}\n\n` +
      "Reponds a la question en t'appuyant sur ces resultats quand ils sont " +
      "pertinents, en citant les URL utilisees.";
  }
  messages.push({ role: "user", content });
  return messages;
}

/** Fonction pure : extrait le texte d'une ligne NDJSON d'Ollama, ou null. */
function parseNdjsonLine(line) {
  const trimmed = (line || "").trim();
  if (!trimmed) return null;
  let obj;
  try {
    obj = JSON.parse(trimmed);
  } catch {
    return null;
  }
  return { piece: obj?.message?.content || "", done: !!obj.done };
}

async function streamChat({ url, model, messages, signal, onToken, options = {} }) {
  const base = (url || "http://localhost:11434").replace(/\/$/, "");
  let res;
  try {
    res = await fetch(`${base}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages, stream: true, options }),
      signal,
    });
  } catch (exc) {
    if (exc.name === "AbortError") throw exc;
    throw new Error(`Ollama injoignable sur ${base} (${exc.message}).`);
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Ollama a repondu ${res.status}${text ? " : " + text.slice(0, 200) : ""}`);
  }
  if (!res.body) throw new Error("Reponse sans corps.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let full = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      const parsed = parseNdjsonLine(line);
      if (!parsed) continue;
      if (parsed.piece) {
        full += parsed.piece;
        if (onToken) onToken(parsed.piece);
      }
      if (parsed.done) return full;
    }
  }
  return full;
}

async function checkHealth(url, model) {
  const base = (url || "http://localhost:11434").replace(/\/$/, "");
  const res = await fetch(`${base}/api/tags`, { signal: AbortSignal.timeout(5000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  const names = (data.models || []).map((m) => m.name);
  const modelBase = (model || "").split(":")[0];
  const present = names.some((n) => n === model || n.split(":")[0] === modelBase);
  return { names, present };
}

module.exports = { DEFAULT_SYSTEM, buildMessages, parseNdjsonLine, streamChat, checkHealth };
