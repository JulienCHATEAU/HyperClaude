"""Pont vers les scripts de ``~/.claude/hooks`` (status line et garde-fou d'usage).

Une seule source de verite : les chemins, la lecture des fichiers et le texte de reset
viennent des scripts eux-memes (charges par chemin), jamais recopies ici.

  - ``usage-statusline.py`` ecrit ``SESSION_DIR/<sessionId>.json`` (modele, contexte %)
    et ``STATE_FILE`` (quotas), et fournit ``next_reset()`` (texte "reset dans 4h47").
  - ``usage-guard.py`` pose ``GUARD_DIR/<sessionId>.json`` (seuils 5 h / 7 j).

Si un script manque ou change de forme, les valeurs sont simplement absentes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Optional

HOOKS_DIR = Path.home() / ".claude" / "hooks"


def _load(filename: str) -> Optional[ModuleType]:
    path = HOOKS_DIR / filename
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


_statusline = _load("usage-statusline.py")
_guard = _load("usage-guard.py")


def _read(path) -> Optional[dict]:
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def session_info(session_id: Optional[str]) -> dict:
    """Modele et contexte % tels qu'affiches par la status line pour cette session."""
    directory = getattr(_statusline, "SESSION_DIR", None)
    if not session_id or not directory:
        return {}
    return _read(Path(directory) / f"{session_id}.json") or {}


def guard_thresholds(session_id: Optional[str]) -> Optional[dict]:
    """Seuils du garde-fou ``{five_hour, seven_day}`` si actif sur cette session."""
    if not session_id or _guard is None:
        return None
    try:
        return _read(_guard.guard_path(session_id))
    except Exception:
        return None


def next_reset() -> Optional[str]:
    """Prochain reset de quota, au texte pres de la status line (ex. "4h47")."""
    if _statusline is None:
        return None
    try:
        text = _statusline.next_reset(_read(_statusline.STATE_FILE) or {})
    except Exception:
        return None
    return text.replace(" | reset dans ", "").strip() or None

