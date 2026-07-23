"""
L'equipe d'agents et son orchestration.

Un COORDINATEUR pilote tout le reste. Il reflechit d'abord au vrai objectif,
puis mobilise l'equipe par cycles :

  Coordinateur (cadre)
    -> Architecte  : pose le plan (fichiers, etapes, risques)
    -> Developpeur : execute en agissant DIRECTEMENT sur les fichiers, le
                     shell et le web (boucle « raisonnement -> outil -> resultat »)
    -> Relecteur   : verifie ce qui a ete livre
  Coordinateur (decide) : objectif atteint -> on termine ; sinon il donne une
                          consigne et relance un cycle.

Tout est diffuse en direct (SSE). A la fin, la reponse, le journal des actions
et la memoire sont ecrits sur disque via `store` : l'IA relit cet historique
et ces faits au tour suivant.
"""

from __future__ import annotations

import json
import re

import requests

import store
import tools

OLLAMA_URL = tools.os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Defaut oriente code et appels d'outils : nettement meilleur que mistral:7b
# pour suivre le protocole JSON du developpeur. Surchargeable via OLLAMA_MODEL.
MODEL = tools.os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")

MAX_STEPS = int(tools.os.environ.get("ATELIER_MAX_STEPS", "16"))
MAX_CYCLES = int(tools.os.environ.get("ATELIER_MAX_CYCLES", "2"))
FILE_EXCERPT_CHARS = 6000


# --------------------------------------------------------------------------
# Acces au modele
# --------------------------------------------------------------------------

def ollama_stream(system, prompt, temperature=0.6, max_tokens=1200):
    """Diffuse la reponse du modele token par token."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": MODEL, "system": system, "prompt": prompt, "stream": True,
                  "options": {"temperature": temperature, "top_p": 0.9,
                              "num_predict": max_tokens}},
            stream=True, timeout=600,
        )
        if r.status_code != 200:
            yield f"[Ollama a repondu {r.status_code}. Verifie le modele '{MODEL}' : ollama list]"
            return
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("response"):
                yield chunk["response"]
            if chunk.get("done"):
                break
    except requests.exceptions.ConnectionError:
        yield "[Ollama injoignable. Lance 'ollama serve' puis reessaie.]"
    except requests.exceptions.Timeout:
        yield "[Delai depasse. Le modele met trop de temps sur cette machine.]"
    except Exception as exc:  # noqa: BLE001
        yield f"[Erreur : {exc}]"


def _complete(system, prompt, temperature=0.5, max_tokens=1000) -> str:
    """Version non diffusee, pour les etapes internes."""
    return "".join(ollama_stream(system, prompt, temperature, max_tokens))


def sse(event, **payload):
    return f"data: {json.dumps({'event': event, **payload}, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------
# Consignes des agents
# --------------------------------------------------------------------------

COORD_BRIEF_SYSTEM = (
    "Tu es le coordinateur d'une equipe de developpement locale : tu piloteras "
    "un architecte, un developpeur (qui agit sur les fichiers) et un relecteur.\n\n"
    "Tu ne codes pas et tu ne detailles pas le plan (c'est l'architecte). Tu cadres.\n"
    "En quelques lignes denses :\n"
    "- L'objectif reel de la demande, en une phrase\n"
    "- Les criteres concrets de reussite\n"
    "- Ce qu'il faut mobiliser et surveiller en priorite\n\n"
    "Appuie-toi sur la memoire et l'historique s'ils sont pertinents."
)

COORD_DECISION_SYSTEM = (
    "Tu es le coordinateur. Le relecteur vient de rendre son verdict sur le cycle en cours.\n\n"
    "Decide si l'objectif est atteint. En deux ou trois phrases : ce qui est acquis, "
    "ce qui manque encore.\n"
    "Termine IMPERATIVEMENT par une ligne exacte :\n"
    "  DECISION: TERMINE      (si le livrable repond a la demande)\n"
    "ou\n"
    "  DECISION: CONTINUER    (s'il faut un nouveau cycle)\n"
    "Si tu ecris CONTINUER, ajoute juste apres une ligne :\n"
    "  CONSIGNE: <ce que le developpeur doit corriger precisement au prochain cycle>"
)

ARCHITECT_SYSTEM = (
    "Tu es l'architecte de l'equipe. Tu ne codes pas : tu cadres le travail.\n\n"
    "A partir de la demande, du brief du coordinateur, de la memoire, de l'historique "
    "et de l'etat de l'espace de travail, produis :\n"
    "- La demande reelle reformulee en une phrase\n"
    "- Un plan en etapes numerotees, concretes et ordonnees par dependance\n"
    "- Les fichiers a creer ou modifier, avec leur role\n"
    "- Les risques et comment les verifier\n\n"
    "Sois dense et operationnel. Pas de code ici : c'est l'etape du developpeur."
)

REVIEWER_SYSTEM = (
    "Tu es le relecteur de l'equipe. Le developpeur vient d'agir sur les fichiers.\n\n"
    "A partir du plan, du journal des actions et de l'etat final, produis :\n"
    "- Ce qui a reellement ete livre (fichiers crees/modifies, commandes lancees)\n"
    "- Ce qui fonctionne et ce dont on est sur\n"
    "- Les limites connues et ce qui reste a faire\n"
    "- La commande pour lancer ou tester, si pertinent\n\n"
    "Appuie-toi uniquement sur le journal reel. N'invente aucun fichier."
)

MEMORY_SYSTEM = (
    "Tu tiens la memoire d'un assistant. A partir de l'echange qui suit, ecris de "
    "1 a 4 faits durables et reutilisables (preferences, decisions, noms de projet, "
    "choix techniques). Un fait par ligne, sans numerotation, court et factuel. "
    "Si rien ne merite d'etre retenu, ecris seulement : RIEN."
)


def _developer_system() -> str:
    return (
        "Tu es le developpeur d'une equipe locale, dans l'esprit de Claude Code : "
        "tu agis DIRECTEMENT sur les fichiers de l'espace de travail, avec acces au "
        "shell et au web.\n\n"
        "A chaque tour, tu reflechis brievement puis tu appelles UN SEUL outil, en "
        "terminant ton message par un bloc JSON delimite ainsi :\n"
        "```json\n"
        '{"tool": "nom_outil", "args": { ... }}\n'
        "```\n\n"
        "Outils disponibles :\n"
        f"{tools.tools_manual()}\n\n"
        "Regles :\n"
        "- Un seul outil par tour. Attends l'observation avant le tour suivant.\n"
        "- Les chemins sont relatifs a l'espace de travail.\n"
        "- Verifie l'existant (list_dir, read_file) avant d'ecrire.\n"
        "- Ecris du code complet et fonctionnel, pas des ebauches.\n"
        "- Quand le plan est realise et verifie, appelle l'outil finish avec un resume.\n"
        "- N'invente jamais le resultat d'un outil : attends-le."
    )


# --------------------------------------------------------------------------
# Extraction de l'appel d'outil
# --------------------------------------------------------------------------

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _extract_tool_call(text: str):
    """Trouve le dernier objet JSON {tool, args} dans la reponse du modele."""
    candidates = _JSON_BLOCK.findall(text)
    if not candidates:
        depth, start = 0, None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start:i + 1])
    for blob in reversed(candidates):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "tool" in obj:
            args = obj.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            return obj["tool"], args
    return None, None


def _parse_decision(text: str):
    """Renvoie (termine: bool, consigne: str)."""
    done = bool(re.search(r"DECISION\s*:\s*TERMINE", text, re.I))
    cont = bool(re.search(r"DECISION\s*:\s*CONTINUER", text, re.I))
    m = re.search(r"CONSIGNE\s*:\s*(.+)", text, re.I | re.S)
    consigne = m.group(1).strip() if m else ""
    # Par defaut, si rien n'est clair, on considere que c'est termine.
    return (done or not cont), consigne


def _workspace_snapshot() -> str:
    snap = tools.list_dir(".")
    if not snap.get("ok"):
        return f"Espace : {tools.get_workspace()} (illisible : {snap.get('error')})"
    lines = [f"Espace de travail : {tools.get_workspace()}"]
    for e in snap["entries"][:40]:
        mark = "/" if e["type"] == "dir" else ""
        lines.append(f"  {e['name']}{mark}")
    if len(snap["entries"]) > 40:
        lines.append(f"  … (+{len(snap['entries']) - 40})")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Etapes reutilisables (generateurs qui diffusent ET renvoient le texte)
# --------------------------------------------------------------------------

def _stream_stage(stage, label, note, system, prompt, temp, tokens):
    """Diffuse une etape d'agent et renvoie son texte complet."""
    yield sse("stage_start", stage=stage, label=label, note=note)
    text = ""
    for tok in ollama_stream(system, prompt, temp, tokens):
        text += tok
        yield sse("token", text=tok)
    yield sse("stage_end", stage=stage)
    return text.strip()


def _developer_loop(conv_id, context, brief, cycle):
    """Boucle d'outils du developpeur. Renvoie la liste des actions resumees."""
    yield sse("stage_start", stage="developpeur", label="Developpeur",
              note=f"cycle {cycle} — agit sur fichiers, shell, web")
    dev_system = _developer_system()
    scratch = f"{context}\n\n[FEUILLE DE ROUTE]\n{brief}\n\n[JOURNAL]\n(vide)"
    actions = []
    finished = False

    for step in range(1, MAX_STEPS + 1):
        yield sse("agent_step", n=step, total=MAX_STEPS)
        reply = ""
        for tok in ollama_stream(dev_system, scratch, 0.35, 900):
            reply += tok
            yield sse("token", text=tok)

        tool, args = _extract_tool_call(reply)
        if tool is None:
            yield sse("tool_note", text="Aucun appel d'outil detecte — rappel du format.")
            scratch += (f"\n\n[ASSISTANT]\n{reply.strip()}\n\n"
                        "[SYSTEME] Termine ton message par un bloc ```json "
                        '{"tool": "...", "args": {...}}```, ou appelle finish.')
            continue

        if tool == "finish":
            summary = (args.get("summary") or "").strip()
            yield sse("tool_call", tool="finish", n=step, args={"summary": summary[:200]})
            store.log_action(conv_id, {"type": "finish", "cycle": cycle, "summary": summary})
            actions.append(f"finish: {summary[:200]}")
            finished = True
            break

        yield sse("tool_call", tool=tool, n=step, args=_preview_args(tool, args))
        result = tools.execute(tool, args)
        store.log_action(conv_id, {"type": "tool", "cycle": cycle, "tool": tool,
                                   "args": _preview_args(tool, args), "result": result})
        actions.append(_summarize_action(tool, args, result))

        observation = _format_observation(tool, args, result)
        yield sse("tool_result", tool=tool, ok=result.get("ok", False),
                  observation=observation[:1500])
        if tool in ("write_file", "edit_file", "make_dir", "delete_path", "move_path") \
                and result.get("ok"):
            yield sse("fs_change", tool=tool,
                      path=result.get("path") or result.get("to", ""),
                      action=result.get("action", tool))

        scratch += (f"\n\n[ASSISTANT]\n{reply.strip()}\n\n"
                    f"[OBSERVATION {tool}]\n{observation[:1800]}")

    if not finished:
        yield sse("tool_note", text=f"Arret apres {MAX_STEPS} tours.")
        actions.append(f"(arret automatique apres {MAX_STEPS} tours)")
    yield sse("stage_end", stage="developpeur")
    return actions


# --------------------------------------------------------------------------
# Orchestration principale
# --------------------------------------------------------------------------

def run_team(conv_id, question, file_name="", file_text=""):
    """Genere le flux SSE de toute la chaine et persiste le resultat."""
    memory = store.memory_block(conv_id)
    history = store.history_block(conv_id)
    snapshot = _workspace_snapshot()

    parts = [f"Demande de l'utilisateur :\n{question}"]
    if file_text:
        excerpt = file_text[:FILE_EXCERPT_CHARS]
        if len(file_text) > FILE_EXCERPT_CHARS:
            excerpt += "\n[...tronque...]"
        parts.append(f"Fichier joint « {file_name} » :\n{excerpt}")
    if memory:
        parts.append(f"[MEMOIRE]\n{memory}")
    if history:
        parts.append(f"[HISTORIQUE DE LA CONVERSATION]\n{history}")
    parts.append(f"[ETAT DE L'ESPACE]\n{snapshot}")
    context = "\n\n".join(parts)

    # ----- Coordinateur : cadrage -----
    yield sse("cycle", label="Coordination")
    brief = yield from _stream_stage(
        "coordinateur", "Coordinateur", "cadre et pilote l'equipe",
        COORD_BRIEF_SYSTEM, context, 0.6, 600)
    store.log_action(conv_id, {"type": "brief", "content": brief})

    all_actions = []
    plan = ""
    consigne = ""
    review = ""

    for cycle in range(1, MAX_CYCLES + 1):
        yield sse("cycle", label=f"Cycle {cycle}")

        # ----- Architecte (plan complet au cycle 1, sinon consigne ciblee) -----
        if cycle == 1:
            plan = yield from _stream_stage(
                "architecte", "Architecte", "pose le plan",
                ARCHITECT_SYSTEM, f"{context}\n\n[BRIEF DU COORDINATEUR]\n{brief}", 0.6, 900)
            store.log_action(conv_id, {"type": "plan", "content": plan})
            dev_brief = plan
        else:
            dev_brief = (f"[PLAN INITIAL]\n{plan}\n\n"
                         f"[CONSIGNE DU COORDINATEUR POUR CE CYCLE]\n{consigne}")

        # ----- Developpeur -----
        actions = yield from _developer_loop(conv_id, context, dev_brief, cycle)
        all_actions.extend(actions)

        # ----- Relecteur -----
        journal = "\n".join(f"- {a}" for a in all_actions) or "(aucune action)"
        review_prompt = (f"{context}\n\n[PLAN]\n{plan}\n\n"
                         f"[JOURNAL DES ACTIONS]\n{journal}\n\n"
                         f"[ETAT FINAL DE L'ESPACE]\n{_workspace_snapshot()}")
        review = yield from _stream_stage(
            "relecteur", "Relecteur", "verifie le livrable",
            REVIEWER_SYSTEM, review_prompt, 0.4, 900)
        store.log_action(conv_id, {"type": "review", "cycle": cycle, "content": review})

        if cycle >= MAX_CYCLES:
            break

        # ----- Coordinateur : decision -----
        decision_prompt = (f"Demande : {question}\n\n[BRIEF]\n{brief}\n\n"
                           f"[VERDICT DU RELECTEUR]\n{review}\n\n"
                           f"[ETAT DE L'ESPACE]\n{_workspace_snapshot()}")
        decision = yield from _stream_stage(
            "coordinateur", "Coordinateur", f"evalue le cycle {cycle}",
            COORD_DECISION_SYSTEM, decision_prompt, 0.4, 400)
        store.log_action(conv_id, {"type": "decision", "cycle": cycle, "content": decision})
        done, consigne = _parse_decision(decision)
        if done or not consigne:
            break

    # ----- Reponse finale, memoire, persistance -----
    journal = "\n".join(f"- {a}" for a in all_actions) or "(aucune action)"
    final = _assemble_final(brief, plan, journal, review)
    store.add_message(conv_id, "assistant", final,
                      stages={"brief": brief, "plan": plan,
                              "journal": all_actions, "review": review})
    store.set_summary(conv_id, review[:1500] or plan[:1500])
    _update_memory(conv_id, question, review or final)

    yield sse("done", conversation=conv_id)


# --------------------------------------------------------------------------
# Helpers de mise en forme
# --------------------------------------------------------------------------

def _preview_args(tool, args):
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > 300 and k in ("content", "replace", "find"):
            out[k] = v[:300] + f"… (+{len(v) - 300} car.)"
        else:
            out[k] = v
    return out


def _format_observation(tool, args, result):
    if not result.get("ok"):
        return f"ECHEC : {result.get('error', 'erreur inconnue')}"
    if tool == "read_file":
        return f"{result['path']} ({result.get('lines', '?')} lignes) :\n{result['content']}"
    if tool == "list_dir":
        rows = [f"{e['name']}{'/' if e['type'] == 'dir' else ''}" for e in result["entries"]]
        return f"{result['path']} :\n" + ("\n".join(rows) if rows else "(vide)")
    if tool == "run_command":
        return f"code={result.get('code')}\n{result.get('output', '')}"
    if tool == "web_search":
        rows = [f"[{i+1}] {r['title']}\n{r['snippet'][:200]}\n{r['url']}"
                for i, r in enumerate(result.get("results", []))]
        return "\n\n".join(rows) or "(aucun resultat)"
    return json.dumps(result, ensure_ascii=False)


def _summarize_action(tool, args, result):
    ok = "ok" if result.get("ok") else "echec"
    if tool in ("write_file", "read_file", "edit_file", "make_dir", "delete_path"):
        return f"{tool} {args.get('path', '')} [{ok}]"
    if tool == "move_path":
        return f"move {args.get('src', '')} -> {args.get('dst', '')} [{ok}]"
    if tool == "run_command":
        return f"run `{args.get('command', '')[:80]}` [{ok}]"
    if tool == "web_search":
        return f"web_search `{args.get('query', '')[:60]}` [{ok}]"
    return f"{tool} [{ok}]"


def _assemble_final(brief, plan, journal, review):
    return (f"## Cadrage\n{brief}\n\n"
            f"## Plan\n{plan}\n\n"
            f"## Actions realisees\n{journal}\n\n"
            f"## Relecture\n{review}").strip()


def _update_memory(conv_id, question, answer):
    prompt = f"Question : {question}\n\nReponse/relecture :\n{answer[:2000]}"
    raw = _complete(MEMORY_SYSTEM, prompt, 0.3, 200).strip()
    if not raw or raw.upper().startswith("RIEN") or raw.startswith("["):
        return
    for line in raw.splitlines():
        fact = re.sub(r'^[\d\.\-\*\s]+', "", line).strip()
        if 4 < len(fact) < 400:
            store.remember(conv_id, fact, scope="conversation")


# --------------------------------------------------------------------------
# Sante d'Ollama
# --------------------------------------------------------------------------

def health():
    r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    names = [m["name"] for m in r.json().get("models", [])]
    return {"status": "connected", "model": MODEL, "model_present": MODEL in names,
            "available": names, "search": "brave" if tools.BRAVE_KEY else "duckduckgo"}
