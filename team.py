"""
L'equipe d'agents et son orchestration.

Un coordinateur reflechit puis pilote l'equipe par cycles :
  Coordinateur (cadre) -> Architecte (plan) -> Developpeur (agit, boucle
  d'outils) -> Relecteur (verifie) -> Coordinateur (decide : terminer ou
  relancer un cycle avec une consigne).

Chaque role tourne sur son propre modele. Tout est diffuse en direct (SSE) ;
a la fin, la reponse, le journal et la memoire sont ecrits sur disque.
"""

from __future__ import annotations

import json
import re

import config
import conversations as convo
import memory
import fileops
import prompts
import workspace as ws
from toolbox import execute
from llm import ollama_stream, complete, sse

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


# --------------------------------------------------------------------------
# Extraction de l'appel d'outil / de la decision
# --------------------------------------------------------------------------

def extract_tool_call(text: str):
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
            return obj["tool"], (args if isinstance(args, dict) else {})
    return None, None


def parse_decision(text: str):
    """Renvoie (termine: bool, consigne: str)."""
    cont = bool(re.search(r"DECISION\s*:\s*CONTINUER", text, re.I))
    done = bool(re.search(r"DECISION\s*:\s*TERMINE", text, re.I))
    m = re.search(r"CONSIGNE\s*:\s*(.+)", text, re.I | re.S)
    return (done or not cont), (m.group(1).strip() if m else "")


def _snapshot() -> str:
    snap = fileops.list_dir(".")
    if not snap.get("ok"):
        return f"Espace : {ws.get_workspace()} (illisible : {snap.get('error')})"
    lines = [f"Espace de travail : {ws.get_workspace()}"]
    for e in snap["entries"][:40]:
        lines.append(f"  {e['name']}{'/' if e['type'] == 'dir' else ''}")
    if len(snap["entries"]) > 40:
        lines.append(f"  … (+{len(snap['entries']) - 40})")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Etapes reutilisables (diffusent ET renvoient le texte)
# --------------------------------------------------------------------------

def _stream_stage(stage, label, note, system, prompt, temp, tokens, model):
    yield sse("stage_start", stage=stage, label=label, note=note, model=model)
    text = ""
    for tok in ollama_stream(system, prompt, temp, tokens, model):
        text += tok
        yield sse("token", text=tok)
    yield sse("stage_end", stage=stage)
    return text.strip()


def _developer_loop(conv_id, context, brief, cycle):
    """Boucle d'outils du developpeur. Renvoie la liste des actions resumees."""
    yield sse("stage_start", stage="developpeur", label="Developpeur",
              note=f"cycle {cycle} — agit sur fichiers, shell, web",
              model=config.MODEL_DEVELOPPEUR)
    dev_system = prompts.developer_system()
    scratch = f"{context}\n\n[FEUILLE DE ROUTE]\n{brief}\n\n[JOURNAL]\n(vide)"
    actions, finished = [], False

    for step in range(1, config.MAX_STEPS + 1):
        yield sse("agent_step", n=step, total=config.MAX_STEPS)
        reply = ""
        for tok in ollama_stream(dev_system, scratch, 0.35, 900, config.MODEL_DEVELOPPEUR):
            reply += tok
            yield sse("token", text=tok)

        tool, args = extract_tool_call(reply)
        if tool is None:
            yield sse("tool_note", text="Aucun appel d'outil detecte — rappel du format.")
            scratch += (f"\n\n[ASSISTANT]\n{reply.strip()}\n\n"
                        "[SYSTEME] Termine ton message par un bloc ```json "
                        '{"tool": "...", "args": {...}}```, ou appelle finish.')
            continue

        if tool == "finish":
            summary = (args.get("summary") or "").strip()
            yield sse("tool_call", tool="finish", n=step, args={"summary": summary[:200]})
            memory.log_action(conv_id, {"type": "finish", "cycle": cycle, "summary": summary})
            actions.append(f"finish: {summary[:200]}")
            finished = True
            break

        yield sse("tool_call", tool=tool, n=step, args=_preview_args(tool, args))
        result = execute(tool, args)
        memory.log_action(conv_id, {"type": "tool", "cycle": cycle, "tool": tool,
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
        yield sse("tool_note", text=f"Arret apres {config.MAX_STEPS} tours.")
        actions.append(f"(arret automatique apres {config.MAX_STEPS} tours)")
    yield sse("stage_end", stage="developpeur")
    return actions


# --------------------------------------------------------------------------
# Orchestration principale
# --------------------------------------------------------------------------

def run_team(conv_id, question, file_name="", file_text="", workspace=""):
    """Genere le flux SSE de toute la chaine et persiste le resultat."""
    if workspace:
        ws.set_active_workspace(workspace)

    mem = memory.memory_block(conv_id)
    history = memory.history_block(conv_id)
    parts = [f"Demande de l'utilisateur :\n{question}"]
    if file_text:
        excerpt = file_text[:config.FILE_EXCERPT_CHARS]
        if len(file_text) > config.FILE_EXCERPT_CHARS:
            excerpt += "\n[...tronque...]"
        parts.append(f"Fichier joint « {file_name} » :\n{excerpt}")
    if mem:
        parts.append(f"[MEMOIRE]\n{mem}")
    if history:
        parts.append(f"[HISTORIQUE DE LA CONVERSATION]\n{history}")
    parts.append(f"[ETAT DE L'ESPACE]\n{_snapshot()}")
    context = "\n\n".join(parts)

    yield sse("cycle", label="Coordination")
    brief = yield from _stream_stage(
        "coordinateur", "Coordinateur", "cadre et pilote l'equipe",
        prompts.COORD_BRIEF_SYSTEM, context, 0.6, 600, config.MODEL_COORDINATEUR)
    memory.log_action(conv_id, {"type": "brief", "content": brief})

    all_actions, plan, consigne, review = [], "", "", ""

    for cycle in range(1, config.MAX_CYCLES + 1):
        yield sse("cycle", label=f"Cycle {cycle}")

        if cycle == 1:
            plan = yield from _stream_stage(
                "architecte", "Architecte", "pose le plan", prompts.ARCHITECT_SYSTEM,
                f"{context}\n\n[BRIEF DU COORDINATEUR]\n{brief}", 0.6, 900,
                config.MODEL_ARCHITECTE)
            memory.log_action(conv_id, {"type": "plan", "content": plan})
            dev_brief = plan
        else:
            dev_brief = (f"[PLAN INITIAL]\n{plan}\n\n"
                         f"[CONSIGNE DU COORDINATEUR POUR CE CYCLE]\n{consigne}")

        actions = yield from _developer_loop(conv_id, context, dev_brief, cycle)
        all_actions.extend(actions)

        journal = "\n".join(f"- {a}" for a in all_actions) or "(aucune action)"
        review_prompt = (f"{context}\n\n[PLAN]\n{plan}\n\n"
                         f"[JOURNAL DES ACTIONS]\n{journal}\n\n"
                         f"[ETAT FINAL DE L'ESPACE]\n{_snapshot()}")
        review = yield from _stream_stage(
            "relecteur", "Relecteur", "verifie le livrable",
            prompts.REVIEWER_SYSTEM, review_prompt, 0.4, 900, config.MODEL_RELECTEUR)
        memory.log_action(conv_id, {"type": "review", "cycle": cycle, "content": review})

        if cycle >= config.MAX_CYCLES:
            break

        decision_prompt = (f"Demande : {question}\n\n[BRIEF]\n{brief}\n\n"
                           f"[VERDICT DU RELECTEUR]\n{review}\n\n"
                           f"[ETAT DE L'ESPACE]\n{_snapshot()}")
        decision = yield from _stream_stage(
            "coordinateur", "Coordinateur", f"evalue le cycle {cycle}",
            prompts.COORD_DECISION_SYSTEM, decision_prompt, 0.4, 400,
            config.MODEL_COORDINATEUR)
        memory.log_action(conv_id, {"type": "decision", "cycle": cycle, "content": decision})
        done, consigne = parse_decision(decision)
        if done or not consigne:
            break

    journal = "\n".join(f"- {a}" for a in all_actions) or "(aucune action)"
    final = _assemble_final(brief, plan, journal, review)
    convo.add_message(conv_id, "assistant", final,
                      stages={"brief": brief, "plan": plan,
                              "journal": all_actions, "review": review})
    memory.set_summary(conv_id, review[:1500] or plan[:1500])
    _update_memory(conv_id, question, review or final)
    yield sse("done", conversation=conv_id)


# --------------------------------------------------------------------------
# Mise en forme
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
    return (f"## Cadrage\n{brief}\n\n## Plan\n{plan}\n\n"
            f"## Actions realisees\n{journal}\n\n## Relecture\n{review}").strip()


def _update_memory(conv_id, question, answer):
    prompt = f"Question : {question}\n\nReponse/relecture :\n{answer[:2000]}"
    raw = complete(prompts.MEMORY_SYSTEM, prompt, 0.3, 200, config.MODEL_MEMOIRE).strip()
    if not raw or raw.upper().startswith("RIEN") or raw.startswith("["):
        return
    for line in raw.splitlines():
        fact = re.sub(r'^[\d\.\-\*\s]+', "", line).strip()
        if 4 < len(fact) < 400:
            memory.remember(conv_id, fact, scope="conversation")
