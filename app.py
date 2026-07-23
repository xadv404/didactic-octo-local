"""
Atelier — equipe d'agents locale sur modele Ollama, facon Claude Code.

L'assistant agit directement sur les fichiers d'un espace de travail (le
Bureau par defaut), avec acces au shell et au web. Chaque conversation est
gardee en memoire : l'IA relit l'historique et les faits retenus avant d'agir,
et indexe tout ce qui a ete fait dans plusieurs fichiers JSON.

Acces protege par mot de passe ; la session tient 15 jours puis redemande
le mot de passe.
"""

from functools import wraps
from pathlib import Path
import json

from flask import (Flask, render_template, request, jsonify, Response,
                   session, redirect, url_for)
from flask_cors import CORS

import store
import tools
import agents

store.init()

app = Flask(__name__)
app.secret_key = store.secret_key()
app.permanent_session_lifetime = store.SESSION_DAYS * 86400
CORS(app, supports_credentials=True)


# --------------------------------------------------------------------------
# Authentification
# --------------------------------------------------------------------------

def _authed() -> bool:
    return bool(session.get("authed")) and not store.session_expired(session.get("authed_at"))


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
    setup = not store.has_password()
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        password = (data.get("password") or "").strip()
        if setup:
            confirm = (data.get("confirm") or "").strip()
            if len(password) < 4:
                return jsonify({"error": "Mot de passe trop court (4 caracteres min)."}), 400
            if password != confirm:
                return jsonify({"error": "Les deux mots de passe different."}), 400
            store.set_password(password)
        else:
            if not store.check_password(password):
                return jsonify({"error": "Mot de passe incorrect."}), 401
        session.permanent = True
        session["authed"] = True
        session["authed_at"] = store._now()
        return jsonify({"ok": True})
    return render_template("login.html", setup=setup, days=store.SESSION_DAYS)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/session")
def session_info():
    if not _authed():
        return jsonify({"authed": False}), 401
    left = store.SESSION_DAYS * 86400 - (store._now() - float(session.get("authed_at", 0)))
    return jsonify({"authed": True, "days_left": round(left / 86400, 1)})


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/manifest.webmanifest")
def manifest():
    """Manifeste PWA — permet « Ajouter à l'écran d'accueil » et le mode autonome."""
    data = {
        "name": "Atelier — équipe d'agents",
        "short_name": "Atelier",
        "description": "Équipe d'agents locale, façon Claude Code.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#14110f",
        "theme_color": "#14110f",
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

@app.route("/api/health")
@login_required
def health():
    try:
        info = agents.health()
        info["workspace"] = str(tools.get_workspace())
        return jsonify(info)
    except Exception:
        return jsonify({"status": "offline", "model": agents.MODEL,
                        "workspace": str(tools.get_workspace())}), 503


@app.route("/api/workspace", methods=["GET", "POST"])
@login_required
def workspace():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        path, err = tools.set_workspace(data.get("path", ""))
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"workspace": str(path)})
    return jsonify({"workspace": str(tools.get_workspace())})


@app.route("/api/files")
@login_required
def files():
    result = tools.list_dir(request.args.get("path", "."))
    if not result.get("ok"):
        return jsonify({"error": result.get("error")}), 400
    return jsonify({"workspace": str(tools.get_workspace()), **result})


@app.route("/api/file")
@login_required
def file_content():
    result = tools.read_file(request.args.get("path", ""))
    if not result.get("ok"):
        return jsonify({"error": result.get("error")}), 400
    return jsonify(result)


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------

@app.route("/api/conversations")
@login_required
def conversations():
    return jsonify({"conversations": store.list_conversations()})


@app.route("/api/conversations", methods=["POST"])
@login_required
def create_conversation():
    conv = store.new_conversation()
    return jsonify({"conversation": {"id": conv["id"], "title": conv["title"],
                                     "created": conv["created"], "updated": conv["updated"],
                                     "message_count": 0}})


@app.route("/api/conversation/<conv_id>/messages")
@login_required
def conversation_messages(conv_id):
    before = request.args.get("before", type=int)
    limit = min(request.args.get("limit", default=25, type=int), 100)
    page = store.page_messages(conv_id, before_seq=before, limit=limit)
    if page.get("title") is None and not page["messages"]:
        return jsonify({"error": "Conversation introuvable."}), 404
    return jsonify(page)


@app.route("/api/conversation/<conv_id>", methods=["DELETE"])
@login_required
def remove_conversation(conv_id):
    return jsonify({"ok": store.delete_conversation(conv_id)})


@app.route("/api/conversation/<conv_id>/rename", methods=["POST"])
@login_required
def rename(conv_id):
    data = request.get_json(silent=True) or {}
    return jsonify({"ok": store.rename_conversation(conv_id, data.get("title", ""))})


@app.route("/api/conversation/<conv_id>/actions")
@login_required
def conversation_actions(conv_id):
    return jsonify({"actions": store.load_actions(conv_id)})


# --------------------------------------------------------------------------
# Execution de l'equipe d'agents
# --------------------------------------------------------------------------

@app.route("/api/run", methods=["POST"])
@login_required
def run():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    conv_id = data.get("conversation") or ""
    file_path = data.get("path") or ""

    if not question:
        return jsonify({"error": "Question vide."}), 400

    # Conversation : reprise ou creation.
    conv = store.load_conversation(conv_id) if conv_id else None
    if conv is None:
        conv = store.new_conversation()
        conv_id = conv["id"]

    # Fichier joint : lecture confinee a l'espace de travail.
    file_name, file_text = "", ""
    if file_path:
        result = tools.read_file(file_path)
        if not result.get("ok"):
            return jsonify({"error": result.get("error")}), 400
        file_text = result["content"]
        file_name = Path(result["path"]).name

    store.add_message(conv_id, "user", question, file=file_name or None)

    def stream():
        yield agents.sse("conversation", id=conv_id,
                         title=store.load_conversation(conv_id)["title"])
        yield from agents.run_team(conv_id, question, file_name, file_text)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print(f"  modele    : {agents.MODEL}")
    print(f"  espace    : {tools.get_workspace()}")
    print(f"  recherche : {'Brave' if tools.BRAVE_KEY else 'DuckDuckGo'}")
    print(f"  donnees   : {store.DATA_DIR}")
    print(f"  session   : {store.SESSION_DAYS} jours")
    print("  ecoute    : http://0.0.0.0:5000\n")
    app.run(host="0.0.0.0", port=5000, threaded=True)
