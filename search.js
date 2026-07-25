"use strict";

/**
 * Recherche web pour le chatbot : interroge DuckDuckGo (pas de cle requise)
 * et parse le HTML renvoye. Le parsing est une fonction pure, testable sans
 * reseau ni Electron.
 */

const RESULT_BLOCK =
  /<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)<\/a>.*?class="result__snippet".*?>(.*?)<\/a>/gs;

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

function unescapeHtml(s) {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

function stripTags(s) {
  return unescapeHtml(s.replace(/<[^>]+>/g, "")).trim();
}

function cleanDdgUrl(href) {
  if (href && href.includes("uddg=")) {
    try {
      const u = new URL(href, "https://duckduckgo.com");
      const uddg = u.searchParams.get("uddg");
      if (uddg) return uddg;
    } catch {
      /* ignore, on retombe sur le href brut */
    }
  }
  return href.startsWith("//") ? "https:" + href : href;
}

/** Fonction pure : extrait les resultats d'une page HTML DuckDuckGo. */
function parseDuckDuckGoHtml(html, limit = 5) {
  const out = [];
  const re = new RegExp(RESULT_BLOCK.source, RESULT_BLOCK.flags);
  let m;
  while (out.length < limit && (m = re.exec(html || ""))) {
    const [, href, title, snippet] = m;
    out.push({ title: stripTags(title), snippet: stripTags(snippet), url: cleanDdgUrl(href) });
  }
  return out;
}

function formatResults(query, results) {
  if (!results || !results.length) return `Recherche : ${query}\n  (rien trouve)`;
  const lines = [`Recherche : ${query}`];
  results.forEach((r, i) => {
    lines.push(`  [${i + 1}] ${r.title}`);
    lines.push(`      ${(r.snippet || "").slice(0, 300)}`);
    lines.push(`      ${r.url}`);
  });
  return lines.join("\n");
}

/** Effectue la recherche reseau et renvoie les resultats parses. */
async function search(query, { limit = 5, timeoutMs = 15000 } = {}) {
  const res = await fetch("https://html.duckduckgo.com/html/", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA },
    body: new URLSearchParams({ q: query }).toString(),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const html = await res.text();
  return parseDuckDuckGoHtml(html, limit);
}

module.exports = { parseDuckDuckGoHtml, cleanDdgUrl, formatResults, search };
