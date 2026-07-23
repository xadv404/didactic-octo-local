"""
Recherche web pour les agents.

Moteur par defaut : Chromium headless via Playwright (adapte aux VPS, passe
mieux les blocages que de simples requetes). Repli sur des requetes HTTP, et
sur l'API Brave si BRAVE_API_KEY est fournie.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urlparse, parse_qs, unquote
import html as htmllib
import re
import os

import requests

import config

RESULTS = config.SEARCH_RESULTS


def search_label() -> str:
    if config.BRAVE_KEY:
        return "brave"
    return "playwright-ddg" if config.SEARCH_ENGINE != "requests" else "ddg-requests"


# --------------------------------------------------------------------------
# Brave (API, si cle)
# --------------------------------------------------------------------------

def _search_brave(query):
    r = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": config.BRAVE_KEY, "Accept": "application/json"},
        params={"q": query, "count": RESULTS}, timeout=20)
    r.raise_for_status()
    out = []
    for item in r.json().get("web", {}).get("results", [])[:RESULTS]:
        out.append({"title": item.get("title", ""),
                    "snippet": re.sub(r"<[^>]+>", "", item.get("description", "")),
                    "url": item.get("url", "")})
    return out


# --------------------------------------------------------------------------
# DuckDuckGo via requetes HTTP (repli)
# --------------------------------------------------------------------------

def _search_ddg_lite(query):
    r = requests.post(
        "https://lite.duckduckgo.com/lite/", data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                 "Referer": "https://lite.duckduckgo.com/"}, timeout=20)
    r.raise_for_status()
    clean = lambda s: htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    links = re.findall(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
    snips = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', r.text, re.S)
    out = []
    for i, (url, title) in enumerate(links[:RESULTS]):
        out.append({"title": clean(title),
                    "snippet": clean(snips[i]) if i < len(snips) else "", "url": url})
    return out


def _search_ddg_html(query):
    r = requests.post(
        "https://html.duckduckgo.com/html/", data={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=20)
    r.raise_for_status()
    clean = lambda s: htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>.*?'
        r'class="result__snippet".*?>(.*?)</a>', r.text, re.S)
    return [{"title": clean(t), "snippet": clean(s), "url": _clean_ddg_url(u)}
            for u, t, s in blocks[:RESULTS]]


# --------------------------------------------------------------------------
# DuckDuckGo via Chromium headless (Playwright)
# --------------------------------------------------------------------------

def _clean_ddg_url(href: str) -> str:
    """DuckDuckGo enveloppe les liens dans /l/?uddg=<url encodee> — on decode."""
    if href and "uddg=" in href:
        try:
            q = parse_qs(urlparse(href).query)
            if "uddg" in q:
                return unquote(q["uddg"][0])
        except Exception:
            pass
    return "https:" + href if href.startswith("//") else href


def _extract_ddg(page) -> list:
    out = []
    for block in page.query_selector_all(".result__body") or []:
        a = block.query_selector("a.result__a")
        if not a:
            continue
        s = block.query_selector(".result__snippet")
        out.append({"title": (a.inner_text() or "").strip(),
                    "snippet": ((s.inner_text() if s else "") or "").strip(),
                    "url": _clean_ddg_url(a.get_attribute("href") or "")})
        if len(out) >= RESULTS:
            break
    return out


def _search_playwright(query):
    from playwright.sync_api import sync_playwright

    proxy = None
    px = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if px:
        proxy = {"server": px}
    ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=config.PW_HEADLESS, proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        try:
            ctx = browser.new_context(user_agent=ua, locale="fr-FR",
                                      viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            for endpoint in ("https://html.duckduckgo.com/html/?q=",
                             "https://lite.duckduckgo.com/lite/?q="):
                page.goto(endpoint + quote_plus(query),
                          wait_until="domcontentloaded", timeout=config.PW_TIMEOUT)
                results = _extract_ddg(page)
                if results:
                    return results
                links = page.query_selector_all("a.result-link")
                if links:
                    snips = page.query_selector_all(".result-snippet")
                    out = [{"title": (a.inner_text() or "").strip(),
                            "snippet": (snips[i].inner_text().strip() if i < len(snips) else ""),
                            "url": _clean_ddg_url(a.get_attribute("href") or "")}
                           for i, a in enumerate(links[:RESULTS])]
                    if out:
                        return out
            return []
        finally:
            browser.close()


# --------------------------------------------------------------------------
# Selection du fournisseur
# --------------------------------------------------------------------------

def web_search(query: str) -> dict:
    if config.BRAVE_KEY:
        providers = [("Brave", _search_brave)]
    elif config.SEARCH_ENGINE != "requests":
        providers = [("DuckDuckGo (Chromium)", _search_playwright),
                     ("DuckDuckGo lite", _search_ddg_lite),
                     ("DuckDuckGo html", _search_ddg_html)]
    else:
        providers = [("DuckDuckGo lite", _search_ddg_lite),
                     ("DuckDuckGo html", _search_ddg_html)]

    problems = []
    for name, fn in providers:
        try:
            results = fn(query)
            if results:
                return {"ok": True, "query": query, "results": results, "engine": name}
            problems.append(f"{name}: aucun resultat")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {type(exc).__name__}")
    return {"ok": False, "query": query, "results": [], "error": " / ".join(problems)}
