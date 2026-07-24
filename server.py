"""
Serveur Flask : authentification, API des conversations, fichiers, execution.

Ne contient que le routage ; toute la logique vit dans les modules dedies
(auth, conversations, memory, workspace, fileops, team, llm).
"""

from functools import wraps
from pathlib import Path
import json

from flask import (Flask, render_template, request, jsonify, Response,
                   session, redirect, url_for)
from flask_cors import CORS

import config
import jsonstore as js
import auth
import conversations as convo
import memory
import workspace as ws
import fileops
import team
import jobs
import llm

js.init()
auth.seed_password()

app = Flask(__name__)
app.secret_key = js.secret_key()
app.permanent_session_lifetime = config.SESSION_DAYS * 86400
app.config["MAX_CONTENT_LENGTH"] = config.UPLOAD_MAX
CORS(app, supports_credentials=True)


@app.errorhandler(413)
def too_large(_e):
    mb = config.UPLOAD_MAX // (1024 * 1024)
    return jsonify({"error": f"Fichier trop volumineux (max {mb} Mo)."}), 413


# --------------------------------------------------------------------------
# Authentification
# --------------------------------------------------------------------------

def _authed() -> bool:
    return bool(session.get("authed")) and not auth.session_expired(session.get("authed_at"))


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if not _authed():
            if request.path.startswith("/api/"):
                return jsonify({"error": "auth", "reason": "session expiree"}), 401
            return redirect(url_for("login"))
        return fn(*a, **k)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    setup = not auth.has_password()
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        password = (data.get("password") or "").strip()
        if setup:
            confirm = (data.get("confirm") or "").strip()
            if len(password) < 4:
                return jsonify({"error": "Mot de passe trop court (4 caracteres min)."}), 400
            if password != confirm:
                return jsonify({"error": "Les deux mots de passe different."}), 400
            auth.set_password(password)
        elif not auth.check_password(password):
            return jsonify({"error": "Mot de passe incorrect."}), 401
        session.permanent = True
        session["authed"] = True
        session["authed_at"] = js.now()
        return jsonify({"ok": True})
    return render_template("login.html", setup=setup, days=config.SESSION_DAYS)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/session")
def session_info():
    if not _authed():
        return jsonify({"authed": False}), 401
    left = config.SESSION_DAYS * 86400 - (js.now() - float(session.get("authed_at", 0)))
    return jsonify({"authed": True, "days_left": round(left / 86400, 1)})


# --------------------------------------------------------------------------
# Pages & manifeste PWA
# --------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": "Atelier — équipe d'agents", "short_name": "Atelier",
        "description": "Équipe d'agents locale, façon Claude Code.",
        "start_url": "/", "scope": "/", "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#14110f", "theme_color": "#14110f",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }
    return Response(json.dumps(data, ensure_ascii=False),
                    mimetype="application/manifest+json")


# --------------------------------------------------------------------------
# Sante, espace de travail, fichiers
# --------------------------------------------------------------------------

def _activate(conv_id):
    ws.set_active_workspace(convo.conversation_workspace(conv_id) or None if conv_id else None)


@app.route("/api/health")
@login_required
def health():
    try:
        info = llm.health()
        info["workspace"] = str(ws.get_workspace())
        return jsonify(info)
    except Exception:
        return jsonify({"status": "offline", "model": config.MODEL,
                        "workspace": str(ws.get_workspace())}), 503


@app.route("/api/workspace", methods=["GET", "POST"])
@login_required
def workspace():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        path, err = ws.set_workspace(data.get("path", ""))
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"workspace": str(path)})
    return jsonify({"workspace": str(ws.get_workspace()),
                    "projects_root": str(config.PROJECTS_ROOT)})


@app.route("/api/files")
@login_required
def files():
    _activate(request.args.get("conversation", ""))
    result = fileops.list_dir(request.args.get("path", "."))
    if not result.get("ok"):
        return jsonify({"error": result.get("error")}), 400
    return jsonify({"workspace": str(ws.get_workspace()), **result})


@app.route("/api/file")
@login_required
def file_content():
    _activate(request.args.get("conversation", ""))
    result = fileops.read_file(request.args.get("path", ""))
    if not result.get("ok"):
        return jsonify({"error": result.get("error")}), 400
    return jsonify(result)


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------

@app.route("/api/conversations")
@login_required
def conversations_list():
    return jsonify({"conversations": convo.list_conversations()})


@app.route("/api/conversations", methods=["POST"])
@login_required
def create_conversation():
    """Cree une conversation avec son dossier dedie. `folder` est optionnel :
    vide -> dossier auto ; sinon dossier existant utilise comme espace."""
    data = request.get_json(silent=True) or {}
    workspace = ""
    folder = (data.get("folder") or "").strip()
    if folder:
        path, _existed, err = ws.prepare_workspace(folder)
        if err:
            return jsonify({"error": err}), 400
        workspace = str(path)
    conv = convo.new_conversation(data.get("title", ""), workspace=workspace)
    return jsonify({"conversation": {"id": conv["id"], "title": conv["title"],
                                     "home": conv["home"], "workspace": conv["workspace"],
                                     "created": conv["created"], "updated": conv["updated"],
                                     "message_count": 0}})


@app.route("/api/conversation/<conv_id>/upload", methods=["POST"])
@login_required
def upload(conv_id):
    """Envoi de fichiers dans l'espace du chat (zip extrait automatiquement)."""
    ws_path = convo.conversation_workspace(conv_id)
    if not ws_path:
        return jsonify({"error": "Conversation introuvable."}), 404
    ws.set_active_workspace(ws_path)
    incoming = request.files.getlist("file")
    if not incoming:
        return jsonify({"error": "Aucun fichier."}), 400
    results, subdir = [], request.form.get("subdir", "")
    for f in incoming:
        data = f.read()
        if not data:
            continue
        results.append(fileops.save_upload(f.filename, data, subdir))
    return jsonify({"results": results, "workspace": ws_path})


@app.route("/api/conversation/<conv_id>/workspace", methods=["POST"])
@login_required
def change_workspace(conv_id):
    data = request.get_json(silent=True) or {}
    path, existed, err = ws.prepare_workspace(data.get("folder", ""))
    if err:
        return jsonify({"error": err}), 400
    if not convo.set_conversation_workspace(conv_id, str(path)):
        return jsonify({"error": "Conversation introuvable."}), 404
    return jsonify({"workspace": str(path), "existed": existed})


@app.route("/api/conversation/<conv_id>/messages")
@login_required
def conversation_messages(conv_id):
    before = request.args.get("before", type=int)
    limit = min(request.args.get("limit", default=25, type=int), 100)
    page = convo.page_messages(conv_id, before_seq=before, limit=limit)
    if page.get("title") is None and not page["messages"]:
        return jsonify({"error": "Conversation introuvable."}), 404
    return jsonify(page)


@app.route("/api/conversation/<conv_id>", methods=["DELETE"])
@login_required
def remove_conversation(conv_id):
    return jsonify({"ok": convo.delete_conversation(conv_id)})


@app.route("/api/conversation/<conv_id>/rename", methods=["POST"])
@login_required
def rename(conv_id):
    data = request.get_json(silent=True) or {}
    return jsonify({"ok": convo.rename_conversation(conv_id, data.get("title", ""))})


@app.route("/api/conversation/<conv_id>/actions")
@login_required
def conversation_actions(conv_id):
    return jsonify({"actions": memory.load_actions(conv_id)})


# --------------------------------------------------------------------------
# Execution de l'equipe d'agents
# --------------------------------------------------------------------------

@app.route("/api/run", methods=["POST"])
@login_required
def run():
    """
    Demarre l'equipe d'agents en arriere-plan et renvoie immediatement un
    identifiant de tache. Le client recupere les evenements par sondage
    (GET /api/job/<id>/events) plutot que par une connexion HTTP longue :
    sur un reseau mobile ou derriere certains proxys, un flux SSE de plusieurs
    minutes est souvent coupe cote reseau ("Load failed"), alors que de courtes
    requetes GET repetees passent sans probleme.
    """
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    conv_id = data.get("conversation") or ""
    file_path = data.get("path") or ""
    if not question:
        return jsonify({"error": "Question vide."}), 400

    conv = convo.load_conversation(conv_id) if conv_id else None
    if conv is None:
        conv = convo.new_conversation()      # dossier dedie auto
        conv_id = conv["id"]

    workspace_path = convo.conversation_workspace(conv_id)
    ws.set_active_workspace(workspace_path or None)

    file_name, file_text = "", ""
    if file_path:
        result = fileops.read_file(file_path)
        if not result.get("ok"):
            return jsonify({"error": result.get("error")}), 400
        file_text = result["content"]
        file_name = Path(result["path"]).name

    convo.add_message(conv_id, "user", question, file=file_name or None)
    title = convo.load_conversation(conv_id)["title"]

    job_id = jobs.create_job()
    jobs.push(job_id, llm.sse("conversation", id=conv_id, title=title))

    def produce(jid):
        for event in team.run_team(conv_id, question, file_name, file_text,
                                   workspace=workspace_path):
            jobs.push(jid, event)

    jobs.run_in_background(job_id, produce)
    return jsonify({"job": job_id, "conversation": conv_id, "title": title})


@app.route("/api/job/<job_id>/events")
@login_required
def job_events(job_id):
    after = request.args.get("after", default=0, type=int)
    result = jobs.poll(job_id, after)
    if result is None:
        return jsonify({"error": "Tache introuvable ou expiree."}), 404
    events, nxt, done, error = result
    return jsonify({"events": events, "next": nxt, "done": done, "error": error})
