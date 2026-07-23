"""
Authentification : mot de passe (hash) et duree de session.

Le mot de passe est seme au premier lancement depuis config.SEED_PASSWORD
(par defaut « amexuhqia1337 », surchargeable via ATELIER_PASSWORD). La session
tient config.SESSION_DAYS jours, puis le mot de passe est redemande.
"""

from __future__ import annotations

import os

from werkzeug.security import generate_password_hash, check_password_hash

import config
import jsonstore as js


def has_password() -> bool:
    return bool(js.read_json(config.AUTH_FILE, {}).get("hash"))


def set_password(password: str) -> None:
    with js._LOCK:
        js.ensure_dirs()
        js.write_json(config.AUTH_FILE, {
            "hash": generate_password_hash(password),
            "updated": js.now(),
        })
        try:
            os.chmod(config.AUTH_FILE, 0o600)
        except OSError:
            pass


def check_password(password: str) -> bool:
    stored = js.read_json(config.AUTH_FILE, {}).get("hash")
    return bool(stored) and check_password_hash(stored, password)


def session_expired(authed_at) -> bool:
    """Vrai si la connexion est absente ou vieille de plus de SESSION_DAYS."""
    if not authed_at:
        return True
    try:
        return (js.now() - float(authed_at)) > config.SESSION_DAYS * 86400
    except (TypeError, ValueError):
        return True


def seed_password() -> None:
    """Definit le mot de passe initial s'il n'existe pas encore."""
    if not has_password() and config.SEED_PASSWORD:
        set_password(config.SEED_PASSWORD)
