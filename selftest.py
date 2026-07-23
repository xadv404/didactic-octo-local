"""
Test de fumee complet, sans Ollama ni reseau.

    python selftest.py

Isole les donnees et l'espace dans des dossiers temporaires, simule le modele,
et verifie : auth (mot de passe seme), conversations + pagination, memoire,
outils fichiers/shell confines, dossier par chat, modeles par role, chaine
complete run_team, et les routes Flask.
"""

import os
import sys
import json
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({
    "ATELIER_DATA": os.path.join(_tmp, "data"),
    "ATELIER_WORKSPACE": os.path.join(_tmp, "desktop"),
    "ATELIER_PROJECTS": os.path.join(_tmp, "projets"),
    "ATELIER_MAX_CYCLES": "1",
    "ATELIER_MODEL_COORDINATEUR": "coord-model",
    "ATELIER_MODEL_ARCHITECTE": "archi-model",
    "ATELIER_MODEL_DEVELOPPEUR": "dev-model",
    "ATELIER_MODEL_RELECTEUR": "review-model",
    "ATELIER_MODEL_MEMOIRE": "mem-model",
})
os.makedirs(os.environ["ATELIER_WORKSPACE"], exist_ok=True)

import config
import jsonstore as js
import auth
import conversations as convo
import memory
import workspace as ws
import fileops
import websearch
import team

js.init()
auth.seed_password()


def check(label):
    print("OK -", label)


# --- auth : mot de passe seme ---
assert auth.has_password()
assert auth.check_password("amexuhqia1337")           # config.SEED_PASSWORD par defaut
assert not auth.check_password("faux")
assert auth.session_expired(None)
assert not auth.session_expired(js.now())
assert auth.session_expired(js.now() - 16 * 86400)
check("auth (mot de passe seme amexuhqia1337, session 15 j)")

# --- conversations + pagination 25 ---
conv = convo.new_conversation(workspace=os.environ["ATELIER_WORKSPACE"])
cid = conv["id"]
for i in range(60):
    convo.add_message(cid, "user" if i % 2 == 0 else "assistant", f"message {i}")
page = convo.page_messages(cid, limit=25)
assert len(page["messages"]) == 25 and page["has_more"]
assert page["messages"][-1]["content"] == "message 59"
older = convo.page_messages(cid, before_seq=page["oldest_seq"], limit=25)
assert older["messages"][-1]["seq"] < page["oldest_seq"]
last = convo.page_messages(cid, before_seq=older["oldest_seq"], limit=25)
assert not last["has_more"] and last["messages"][0]["seq"] == 1
check("conversations + pagination (25/page, remontee)")

# --- index multi-json + memoire ---
assert config.INDEX_FILE.exists()
assert (config.ACTIONS_DIR / f"{cid}.json").exists()
assert (config.MEMORY_DIR / f"{cid}.json").exists()
memory.log_action(cid, {"type": "tool", "tool": "write_file"})
assert len(memory.load_actions(cid)) == 1
memory.remember(cid, "prefere le francais")
memory.remember(cid, "projet atelier", scope="global")
memory.set_summary(cid, "resume de test")
mem = memory.memory_block(cid)
assert "francais" in mem and "atelier" in mem and "test" in mem
assert "message 59" in memory.history_block(cid)
check("index multi-JSON + memoire")

# --- outils fichiers confines ---
ws.set_active_workspace(os.environ["ATELIER_WORKSPACE"])
assert fileops.write_file("proj/a.txt", "bonjour")["ok"]
assert fileops.read_file("proj/a.txt")["content"] == "bonjour"
assert fileops.edit_file("proj/a.txt", "bonjour", "salut")["ok"]
assert fileops.read_file("proj/a.txt")["content"] == "salut"
assert fileops.make_dir("proj/sub")["ok"]
assert fileops.move_path("proj/a.txt", "proj/sub/b.txt")["ok"]
assert fileops.read_file("../../../etc/passwd")["ok"] is False
assert fileops.write_file("/etc/evil", "x")["ok"] is False
r = fileops.run_command("echo coucou")
assert r["ok"] and "coucou" in r["output"]
assert fileops.run_command("rm -rf /")["ok"] is False
check("outils fichiers/shell confines + garde-fous")

# --- un dossier par chat (isolation) ---
a, existed, err = ws.prepare_workspace("projetA")
assert err is None and not existed and str(a).startswith(os.environ["ATELIER_PROJECTS"])
b, _, _ = ws.prepare_workspace("projetB")
ws.set_active_workspace(str(a)); fileops.write_file("x.txt", "A")
ws.set_active_workspace(str(b)); fileops.write_file("y.txt", "B")
ws.set_active_workspace(str(a))
assert [e["name"] for e in fileops.list_dir(".")["entries"]] == ["x.txt"]
check("un dossier par chat (isolation)")

# --- extraction outil + decision ---
name, args = team.extract_tool_call('a ```json\n{"tool":"write_file","args":{"path":"a","content":"x"}}\n```')
assert name == "write_file" and args["path"] == "a"
done, cons = team.parse_decision("bla\nDECISION: CONTINUER\nCONSIGNE: corrige X")
assert done is False and "X" in cons
assert team.parse_decision("ok\nDECISION: TERMINE")[0] is True
check("extraction outil + decision")

# --- recherche web (parsing, sans reseau) ---
assert websearch._clean_ddg_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fe.com%2Fa") == "https://e.com/a"
assert websearch.search_label() in ("playwright-ddg", "ddg-requests", "brave")
check("recherche web (decodage URL + libelle moteur)")

# --- chaine complete run_team avec modele simule ---
calls = iter([
    '```json\n{"tool":"write_file","args":{"path":"note.md","content":"salut"}}\n```',
    '```json\n{"tool":"finish","args":{"summary":"fait"}}\n```',
])
seen = []
def fake(system, prompt, temperature=0.6, max_tokens=1200, model=None):
    s = system.lower()
    role = ("developpeur" if "tu es le developpeur" in s else
            "coordinateur" if ("coordinateur d'une equipe" in s or "vient de rendre" in s) else
            "architecte" if "tu es l'architecte" in s else
            "relecteur" if "tu es le relecteur" in s else
            "memoire" if "tu tiens la memoire" in s else "?")
    seen.append((role, model))
    if role == "developpeur":
        try: yield next(calls)
        except StopIteration: yield '```json\n{"tool":"finish","args":{"summary":"x"}}\n```'
    elif role == "memoire": yield "RIEN"
    else: yield "[simule]"
team.ollama_stream = fake
team.complete = lambda system, prompt, t=0.5, mx=1000, model=None: "".join(fake(system, prompt, t, mx, model))

chat = convo.new_conversation(workspace=str(a))
cid2 = chat["id"]
convo.add_message(cid2, "user", "ecris une note")
stage_models = {}
for chunk in team.run_team(cid2, "ecris une note", workspace=str(a)):
    e = json.loads(chunk[6:])
    if e["event"] == "stage_start":
        stage_models.setdefault(e["stage"], e.get("model"))
assert (a / "note.md").is_file(), "note.md non ecrite dans le dossier du chat"
assert stage_models == {"coordinateur": "coord-model", "architecte": "archi-model",
                        "developpeur": "dev-model", "relecteur": "review-model"}, stage_models
by_role = {}
for role, model in seen:
    by_role.setdefault(role, set()).add(model)
assert by_role["memoire"] == {"mem-model"}
last_msg = convo.page_messages(cid2, limit=25)["messages"][-1]
assert last_msg["role"] == "assistant" and "Actions realisees" in last_msg["content"]
check("chaine complete run_team (fichier ecrit, modele par role, persistance)")

# --- routes Flask ---
ws.set_active_workspace(None)
from server import app
c = app.test_client()
assert c.get("/api/conversations").status_code == 401
assert c.post("/login", json={"password": "amexuhqia1337"}).get_json().get("ok")  # deja seme
assert c.get("/").status_code == 200
r = c.post("/api/conversations", json={"title": "S", "folder": "site"}).get_json()
ncid = r["conversation"]["id"]
assert r["conversation"]["workspace"].endswith("site")
assert c.post("/api/conversations", json={"title": "x"}).status_code == 400  # dossier requis
ws.set_active_workspace(r["conversation"]["workspace"]); fileops.write_file("i.html", "<h1>ok</h1>")
ws.set_active_workspace(None)
listing = c.get(f"/api/files?conversation={ncid}").get_json()
assert any(e["name"] == "i.html" for e in listing["entries"])
mani = c.get("/manifest.webmanifest")
assert mani.status_code == 200 and "manifest+json" in mani.content_type
assert c.get("/api/health").status_code in (200, 503)
check("routes Flask (auth semee, conversations, fichiers scopes, manifeste)")

print("\nTOUS LES TESTS PASSENT")
