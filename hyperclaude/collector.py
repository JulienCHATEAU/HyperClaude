"""Collecte et normalisation de l'etat des sessions Claude Code (lot L0).

Coeur transverse du widget HyperClaude, reutilise par tous les paliers :

  1. Enumere les fichiers d'etat natifs ecrits par Claude Code :
     ``~/.claude/sessions/<pid>.json``.
  2. Filtre les sessions mortes (process disparu).
  3. Resout le mapping ``pid -> tty`` (fenetre Hyper) via ``ps``.
  4. Trie pour l'affichage : en attente, puis en cours, puis au repos.

Aucune ecriture nulle part : le module ne fait que lire des fichiers et interroger ``ps``.
Le format de ``sessions/<pid>.json`` n'est pas contractuel (teste sur Claude Code 2.1.210) ;
le parsing est donc defensif et tolere les champs manquants.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import claude_hooks

# Emplacement des fichiers d'etat natifs de Claude Code.
SESSIONS_DIR = Path.home() / ".claude" / "sessions"

# Journaux de conversation (un .jsonl par session) : porte le titre genere par l'IA.
PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Taille max lue en fin de journal pour retrouver le dernier titre (les `ai-title`
# sont emis regulierement, donc presents pres de la fin).
_TITLE_TAIL_BYTES = 1_000_000

# Au-dela de ce delai sans mise a jour, une session encore vivante est marquee "stale"
# (information seulement - elle reste affichee, cf. note sur `alive` plus bas).
STALE_AFTER_MS = 30 * 60 * 1000  # 30 min

# Ordre d'affichage : ce qui reclame une action d'abord.
_STATUS_ORDER = {"waiting": 0, "busy": 1, "idle": 2, "unknown": 3}


@dataclass
class SessionEntry:
    """Etat normalise d'une session Claude Code."""

    pid: int
    session_id: Optional[str] = None
    name: Optional[str] = None       # nom derive (ex. repositories-91)
    title: Optional[str] = None      # titre genere par l'IA (celui de /resume)
    cwd: Optional[str] = None
    status: str = "unknown"          # waiting | busy | idle | unknown
    waiting_for: Optional[str] = None
    updated_at: Optional[int] = None  # epoch ms
    version: Optional[str] = None
    tty: Optional[str] = None         # ex. "ttys016" ; None si non resolu
    shell_pid: Optional[int] = None   # pid du shell parent (= pty.pid cote Hyper)
    alive: bool = False               # process reellement vivant
    focusable: bool = False           # tty resolu -> fenetre Hyper ciblable
    stale: bool = False               # pas de MaJ depuis STALE_AFTER_MS
    remote: bool = False              # session ouverte depuis claude.ai via /rc
    model: Optional[str] = None       # modele affiche par la status line
    context_percent: Optional[float] = None
    guard_five_hour: Optional[int] = None   # seuils du garde-fou d'usage, si actif
    guard_seven_day: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _pid_alive(pid: int) -> bool:
    """Le process existe-t-il ? EPERM = existe mais pas a nous -> vivant."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False
    return True


def _build_ps_map() -> Dict[int, Tuple[Optional[int], str]]:
    """Retourne ``{pid: (ppid, tty)}`` pour tous les process, via un seul appel ``ps``.

    ``ps -o tty=`` rend ``ttys016`` pour un process attache a un terminal, ``??`` sinon.
    """
    out = subprocess.run(
        ["ps", "-Ao", "pid=,ppid=,tty="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    ps_map: Dict[int, Tuple[Optional[int], str]] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        ps_map[pid] = (ppid, parts[2].strip())
    return ps_map


def _resolve_tty(pid: int, ps_map: Dict[int, Tuple[Optional[int], str]]) -> Optional[str]:
    """tty de la session : celui du process ``claude`` lui-meme, avec repli sur le parent.

    Retourne un tty du type ``ttysNNN``, ou None si aucun terminal n'est resolu
    (session detachee, tmux, SSH... -> non ciblable).
    """
    seen = set()
    cur: Optional[int] = pid
    # On remonte au plus 3 niveaux (claude -> shell -> ...) pour trouver un vrai tty.
    for _ in range(3):
        if cur is None or cur in seen or cur not in ps_map:
            break
        seen.add(cur)
        ppid, tty = ps_map[cur]
        if tty and tty.startswith("ttys"):
            return tty
        cur = ppid
    return None


def _find_session_log(session_id: str) -> Optional[Path]:
    """Localise le journal `<sessionId>.jsonl` dans les dossiers de projets."""
    if not session_id or not PROJECTS_DIR.is_dir():
        return None
    matches = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None


def _read_ai_title(path: Path) -> Optional[str]:
    """Retourne le dernier titre genere par l'IA (`type: ai-title`) du journal, a defaut le
    dernier prompt (`type: last-prompt`) : une session lancee par /rc n'a pas de titre IA.

    Lit seulement la fin du fichier (jusqu'a `_TITLE_TAIL_BYTES`) et scanne les lignes
    de la fin vers le debut - pas de parsing integral d'un gros JSONL.
    """
    try:
        size = path.stat().st_size
        to_read = min(size, _TITLE_TAIL_BYTES)
        with path.open("rb") as fh:
            fh.seek(size - to_read)
            data = fh.read(to_read)
    except OSError:
        return None
    last_prompt = None
    for line in reversed(data.splitlines()):
        if b'"ai-title"' not in line and (last_prompt or b'"last-prompt"' not in line):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") == "ai-title" and entry.get("aiTitle"):
            return entry["aiTitle"]
        if entry.get("type") == "last-prompt" and not last_prompt:
            last_prompt = entry.get("lastPrompt")
    return last_prompt


def _parse_session_file(path: Path) -> Optional[SessionEntry]:
    """Parse un ``sessions/<pid>.json`` en SessionEntry (tolerant aux champs manquants)."""
    try:
        pid = int(path.stem)
    except ValueError:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Fichier illisible ou en cours d'ecriture : on ignore ce cycle.
        return None
    if not isinstance(raw, dict):
        return None

    status = raw.get("status") or "unknown"
    if status not in _STATUS_ORDER:
        status = "unknown"

    return SessionEntry(
        pid=raw.get("pid", pid),
        session_id=raw.get("sessionId"),
        name=raw.get("name"),
        cwd=raw.get("cwd"),
        status=status,
        waiting_for=raw.get("waitingFor"),
        updated_at=raw.get("updatedAt"),
        version=raw.get("version"),
        remote=raw.get("entrypoint") == "sdk-cli",
    )


def collect(include_dead: bool = False, now_ms: Optional[int] = None) -> List[SessionEntry]:
    """Retourne les sessions Claude Code normalisees, triees pour l'affichage.

    Par defaut, seules les sessions vivantes sont retournees (``include_dead=False``).

    Note sur ``alive`` : la vivacite fait autorite sur l'existence du **process**
    (``kill -0``), pas sur la fraicheur du fichier - une session ``idle`` ouverte depuis
    des heures reste une vraie session. La peremption (``stale``) est une information
    complementaire, jamais un motif d'exclusion.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    if not SESSIONS_DIR.is_dir():
        return []

    ps_map = _build_ps_map()
    entries: List[SessionEntry] = []

    for path in SESSIONS_DIR.glob("*.json"):
        entry = _parse_session_file(path)
        if entry is None:
            continue

        entry.alive = _pid_alive(entry.pid)
        if not entry.alive and not include_dead:
            continue

        entry.tty = _resolve_tty(entry.pid, ps_map)
        # pid du shell parent (zsh lance par node-pty) : pivot de correlation avec Hyper.
        entry.shell_pid = ps_map.get(entry.pid, (None, ""))[0]
        entry.focusable = entry.tty is not None
        if entry.updated_at:
            entry.stale = (now_ms - entry.updated_at) > STALE_AFTER_MS

        if entry.session_id:
            log = _find_session_log(entry.session_id)
            if log:
                entry.title = _read_ai_title(log)

        info = claude_hooks.session_info(entry.session_id)
        entry.model = info.get("model") or None
        entry.context_percent = info.get("context_percent")
        guard = claude_hooks.guard_thresholds(entry.session_id) or {}
        entry.guard_five_hour = guard.get("five_hour")
        entry.guard_seven_day = guard.get("seven_day")

        entries.append(entry)

    entries.sort(key=lambda e: (_STATUS_ORDER.get(e.status, 3), (e.name or "").lower()))
    return entries


def to_json(entries: List[SessionEntry], indent: int = 2) -> str:
    """Serialise une liste de SessionEntry en JSON (consommable par le rendu du widget)."""
    return json.dumps([e.to_dict() for e in entries], indent=indent, ensure_ascii=False)


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Collecte l'etat des sessions Claude Code (socle L0 HyperClaude).",
    )
    parser.add_argument(
        "--include-dead",
        action="store_true",
        help="Inclure aussi les sessions dont le process n'est plus vivant.",
    )
    args = parser.parse_args(argv)

    print(to_json(collect(include_dead=args.include_dead)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
