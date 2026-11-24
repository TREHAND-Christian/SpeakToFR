"""Lecture automatique des reponses de Claude Desktop (accessibilite Windows / UI Automation).

Principe :
- un thread surveille la fenetre Claude Desktop (claude.exe) ;
- quand la derniere reponse de Claude passe de "en cours" a "terminee"
  (la barre d'actions du message, avec "Lire a voix haute", apparait), son texte
  est extrait et envoye a SpeakToFR via le signal `message_ready`.

Test sans lecture (Claude Desktop ouvert) :
    python -m codex_tts.services.claude_desktop
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

try:
    import uiautomation as auto
except ImportError:  # module optionnel : la fonction reste simplement inactive
    auto = None

log = logging.getLogger(__name__)

# --- Libelles de l'interface Claude Desktop (francais) : a adapter si la langue change ---
PROCESS_NAME = "claude.exe"
MESSAGES_GROUP = "Messages de la conversation"
MESSAGE_PREFIX = "Message "
CLAUDE_PREFIX = "Claude a répondu"
STREAMING_PREFIX = "Message en cours"  # nom du groupe pendant la generation de la reponse
ACTIONS_TOOLBAR = "Actions du message"

POLL_SECONDS = 1.0
_LIST_MARKER = re.compile(r"^(\d+\.|•|-)$")
_NO_SPACE_BEFORE = (" ", "\xa0", ",", ".", ";", ":", ")", "!", "?", "»", "’", "'")
_NO_SPACE_AFTER = (" ", "\xa0", "(", "«", "’", "'")


# ----------------------------------------------------------------------------
# Fenetre Claude Desktop
# ----------------------------------------------------------------------------
def _exe_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)
    return ""


def _find_claude_window():
    root = auto.GetRootControl()
    for w in root.GetChildren():
        try:
            if w.ControlTypeName != "WindowControl":
                continue
            if _exe_name(w.ProcessId) == PROCESS_NAME:
                return w
        except Exception:
            continue
    return None


# ----------------------------------------------------------------------------
# Extraction du texte
# ----------------------------------------------------------------------------
def _join(parts: list[str]) -> str:
    out = ""
    for p in parts:
        if not out:
            out = p
        elif out.endswith(_NO_SPACE_AFTER) or p.startswith(_NO_SPACE_BEFORE):
            out += p
        else:
            out += " " + p
    return out.strip()


def _inline_text(ctrl) -> str:
    """Texte d'un element en ligne (gras, code...) : son nom est vide, le texte est dans ses enfants."""
    parts: list[str] = []
    for c in ctrl.GetChildren():
        n = (c.Name or "")
        parts.append(n if n else _inline_text(c))
    return "".join(parts)


def _walk(ctrl, paragraphs: list[str], button_names: set[str], state: dict) -> None:
    """Parcourt les enfants : les TextControl voisins forment un meme paragraphe."""
    buf: list[str] = []
    only_code = [True]  # le paragraphe ne contient que du code (ligne de commande, bloc) : non lu

    def flush() -> None:
        if buf:
            text = _join(buf)
            skip = only_code[0]
            buf.clear()
            only_code[0] = True
            if text and not skip and not _LIST_MARKER.match(text):
                paragraphs.append(text)

    for child in ctrl.GetChildren():
        kind = child.ControlTypeName
        name = (child.Name or "").strip()
        if kind == "ToolBarControl":
            flush()
            if name == ACTIONS_TOOLBAR:
                state["complete"] = True
            continue
        if state.get("complete"):
            continue  # horodatage etc. apres la barre d'actions
        if kind == "ButtonControl":
            flush()
            if name:
                button_names.add(name)
            continue
        if kind == "TextControl":
            if name.startswith(CLAUDE_PREFIX):
                state["claude"] = True
                continue
            text = name or _inline_text(child).strip()
            if text:
                buf.append(text)
                if child.LocalizedControlType != "code":
                    only_code[0] = False
            continue
        if name and child.GetFirstChildControl() is None:
            buf.append(name)
            only_code[0] = False
            continue
        flush()
        _walk(child, paragraphs, button_names, state)
    flush()


def _find_message_groups(ctrl, depth: int = 0, max_depth: int = 8) -> list:
    """Groupes 'Message N sur M' (peuvent etre imbriques dans des groupes sans nom)."""
    found = []
    if depth > max_depth:
        return found
    for c in ctrl.GetChildren():
        if c.ControlTypeName != "GroupControl":
            continue
        if (c.Name or "").startswith(MESSAGE_PREFIX):
            found.append(c)
        else:
            found.extend(_find_message_groups(c, depth + 1, max_depth))
    return found


LAST_REASON = ""  # pour le diagnostic en ligne de commande
_MSG_NUM = re.compile(r"Message (\d+) sur (\d+)")


def _scan(win) -> Optional[dict]:
    """Etat du dernier message de la conversation affichee (None si la liste est introuvable)."""
    global LAST_REASON
    group = win.GroupControl(Name=MESSAGES_GROUP)
    if not group.Exists(0, 0):
        LAST_REASON = f"liste '{MESSAGES_GROUP}' introuvable"
        return None
    msgs = _find_message_groups(group)
    if not msgs:
        LAST_REASON = "aucun groupe 'Message N sur M' dans la liste"
        return None
    last = msgs[-1]
    paragraphs: list[str] = []
    buttons: set[str] = set()
    state: dict = {}
    _walk(last, paragraphs, buttons, state)
    paragraphs = [p for p in paragraphs if p not in buttons]
    # Un titre sans ponctuation finale serait colle a la phrase suivante par la synthese vocale.
    paragraphs = [p if p[-1] in ".!?:;…»)" else p + "." for p in paragraphs]
    m = _MSG_NUM.search(last.Name or "")
    LAST_REASON = f"'{last.Name}'"
    return {
        "name": last.Name or "",
        "total": int(m.group(2)) if m else None,
        "claude": bool(state.get("claude")),
        "complete": bool(state.get("complete")),
        "text": "\n\n".join(paragraphs),
    }


def _read_last_claude_message(win) -> Optional[tuple[bool, str]]:
    """Pour le diagnostic : (terminee, texte) si le dernier message vient de Claude."""
    global LAST_REASON
    info = _scan(win)
    if info is None:
        return None
    if not info["claude"]:
        LAST_REASON = f"'{info['name']}' n'est pas une reponse de Claude"
        return None
    return info["complete"], info["text"]


# ----------------------------------------------------------------------------
# Surveillance
# ----------------------------------------------------------------------------
class ClaudeDesktopReader(QObject):
    """Appelle `callback(texte)` (dans le thread de l'interface) quand une reponse vient de se terminer."""

    _ready = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.callback = None
        self._enabled = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ready.connect(self._deliver)  # methode de cet objet : livraison dans le thread de l'interface

    @property
    def available(self) -> bool:
        return auto is not None

    def _deliver(self, text: str) -> None:
        if self.callback is not None:
            try:
                self.callback(text)
            except Exception:
                log.exception("Lecture de la reponse Claude Desktop")

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self._start()
        else:
            self._stop.set()

    def _start(self) -> None:
        if auto is None:
            log.warning("Module uiautomation absent : lecture automatique de Claude Desktop indisponible")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ClaudeDesktopReader", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        log.info("Claude Desktop : surveillance demarree")
        pending = False        # derniere reponse vue "en cours" : a lire quand elle sera terminee
        prev_total = None      # nombre de messages au passage precedent
        last_key = None        # derniere reponse lue
        last_state = None
        window_seen = False
        with auto.UIAutomationInitializerInThread():
            while not self._stop.wait(POLL_SECONDS):
                try:
                    win = _find_claude_window()
                    if win is None:
                        if window_seen:
                            log.info("Claude Desktop : fenetre introuvable")
                        window_seen, pending, prev_total = False, False, None
                        continue
                    if not window_seen:
                        log.info("Claude Desktop : fenetre trouvee")
                        window_seen = True
                    info = _scan(win)
                    if info is None:
                        pending, prev_total = False, None
                        continue
                    state = (info["name"], info["claude"], info["complete"])
                    if state != last_state:
                        log.info("Claude Desktop : %s | Claude=%s | terminee=%s", *state)
                        last_state = state
                    if info["name"].startswith(STREAMING_PREFIX):
                        pending = True  # reponse en cours de generation : a lire quand elle sera terminee
                        continue
                    total = info["total"]
                    advanced = (prev_total is not None and total is not None
                                and 0 < total - prev_total <= 3)
                    if info["claude"]:
                        key = (total, info["text"][:80])
                        if not info["complete"]:
                            pending = True
                        elif (pending or advanced) and key != last_key and info["text"].strip():
                            pending = False
                            last_key = key
                            log.info("Claude Desktop : reponse terminee (%d car.)", len(info["text"]))
                            self._ready.emit(info["text"])
                    else:
                        pending = False
                    if total is not None:
                        prev_total = total
                except Exception:
                    log.exception("Surveillance de Claude Desktop")


def _dump_tree(ctrl, depth: int = 0, out=None) -> None:
    """Diagnostic : arbre complet (types, classes, noms, valeurs) d'un message."""
    for c in ctrl.GetChildren():
        extra = ""
        try:
            extra = f" class={c.ClassName!r} role={c.LocalizedControlType!r}"
        except Exception:
            pass
        out.write(f"{'  ' * depth}{c.ControlTypeName}{extra} name={(c.Name or '')[:100]!r}\n")
        _dump_tree(c, depth + 1, out)


if __name__ == "__main__":
    import sys
    if "--tree" in sys.argv:
        with auto.UIAutomationInitializerInThread():
            w = _find_claude_window()
            g = w.GroupControl(Name=MESSAGES_GROUP)
            last = _find_message_groups(g)[-1]  # derniere reponse (terminee)
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tree_dump.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{last.Name}\n")
                _dump_tree(last, 1, f)
            print("Ecrit :", os.path.abspath(path))
        raise SystemExit
    if auto is None:
        raise SystemExit("pip install uiautomation")
    with auto.UIAutomationInitializerInThread():
        w = _find_claude_window()
        if w is None:
            raise SystemExit("Fenetre Claude Desktop introuvable.")
        r = _read_last_claude_message(w)
        if r is None:
            raise SystemExit("Rien a lire : " + LAST_REASON)
        print("Message :", LAST_REASON, "| terminee :", r[0])
        print("-" * 60)
        print(r[1])
