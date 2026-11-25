"""Lecture automatique des reponses de Claude Desktop (accessibilite Windows / UI Automation).

Principe :
- un thread surveille la fenetre Claude Desktop (claude.exe) ;
- quand la derniere reponse de Claude passe de "en cours" a "terminee"
  (la barre d'actions du message, avec "Lire a voix haute", apparait), son texte
  est extrait et envoye a SpeakToFR (`callback`) ;
- quand une conversation est ouverte ou changee (titre du document "Titre - Claude"),
  sa derniere reponse est seulement chargee (`on_loaded`) : le prochain Play la lira ;
- pendant la generation, chaque paragraphe termine (texte intermediaire entre deux outils,
  ou paragraphe deja suivi d'un autre) est envoye tout de suite (`on_partial`) ; a la fin,
  seule la partie pas encore envoyee est a lire. Les lignes d'etat ("Utilisant ...") sont ignorees.

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
# Lignes d'etat des outils (trop repetitives pour etre lues) ; les autres lignes d'etape resument le travail
_TOOL_LINE_PREFIXES = ("utilisant ", "utilisé ", "using ", "used ", "running ", "ran ")
# Etat ajoute en texte cache (lecteurs d'ecran) au nom d'une etape qui tourne
_RUNNING_SUFFIX = re.compile(r"[\s,.:;-]*(en cours d['’]ex[ée]cution|en cours|in progress|running)\s*$", re.IGNORECASE)


def clean_status(name: str) -> str:
    """Libelle d'une ligne d'etape sans son etat ("... en cours d'execution")."""
    return _RUNNING_SUFFIX.sub("", (name or "").strip()).strip()


def _visible_label(button) -> str:
    """Texte visible d'un bouton de ligne d'etape (sans les textes caches 'sr-only')."""
    parts: list[str] = []
    try:
        for group in button.GetChildren():
            try:
                if "sr-only" in (group.ClassName or ""):
                    continue
            except Exception:
                pass
            if group.ControlTypeName == "TextControl":
                if (group.Name or "").strip():
                    parts.append(group.Name.strip())
                continue
            for c in group.GetChildren():
                if c.ControlTypeName == "TextControl" and (c.Name or "").strip():
                    parts.append(c.Name.strip())
    except Exception:
        return ""
    return " ".join(parts)
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
        if kind == "StatusBarControl":
            continue  # annonce pour lecteur d'ecran (doublon de la ligne d'etat d'un outil)
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
                try:
                    if "group/status-line" in (ctrl.ClassName or ""):
                        # Ligne d'etape (resume du travail) : libelle visible, sans "en cours d'execution"
                        label = clean_status(_visible_label(child) or name)
                        if label:
                            state.setdefault("status", []).append(label)
                except Exception:
                    pass
            paragraphs.append(None)  # repere : ce qui precede est termine (outil, ligne d'etat...)
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
    items: list = []  # paragraphes, et reperes None (bouton, ligne d'etat d'un outil)
    buttons: set[str] = set()
    state: dict = {}
    _walk(last, items, buttons, state)
    items = [p for p in items if p is None or p not in buttons]
    # Un paragraphe suivi d'autre chose est termine ; le tout dernier peut encore s'ecrire
    trailing_open = bool(items) and items[-1] is not None
    paragraphs = [p for p in items if p is not None]
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
        "paragraphs": paragraphs,
        "done_count": len(paragraphs) - (1 if trailing_open else 0),
        "status": list(dict.fromkeys(state.get("status", []))),
    }


def is_tool_line(name: str) -> bool:
    """Ligne d'etat d'un outil ("Utilisant Windows-MCP...") : pas lue."""
    return (name or "").strip().lower().startswith(_TOOL_LINE_PREFIXES)


def _conversation_title(win, max_depth: int = 12) -> str:
    """Titre de la conversation affichee : nom du document web ("Titre - Claude")."""

    def walk(ctrl, depth: int) -> str:
        if depth > max_depth:
            return ""
        for c in ctrl.GetChildren():
            try:
                if c.ControlTypeName == "DocumentControl":
                    name = (c.Name or "").strip()
                    if name:
                        return name
                    continue
                found = walk(c, depth + 1)
                if found:
                    return found
            except Exception:
                continue
        return ""

    try:
        return walk(win, 0)
    except Exception:
        return ""


class ResponseTracker:
    """Decide a chaque passage s'il faut lire (nouvelle reponse) ou seulement charger la derniere reponse."""

    def __init__(self) -> None:
        self.pending = False      # reponse vue "en cours" : a lire quand elle sera terminee
        self.prev_total = None    # nombre de messages au passage precedent
        self.last_key = None      # derniere reponse lue ou chargee
        self.conv = None          # titre de la conversation affichee
        self.spoken: list[str] = []  # paragraphes deja envoyes pendant la generation
        self.spoken_status: set[str] = set()  # lignes d'etape deja envoyees
        # Passage precedent : un texte n'est envoye que s'il n'a pas bouge depuis (le texte
        # s'affiche progressivement et les lignes d'etape sont animees d'un libelle a l'autre)
        self.prev_paras: list[str] = []
        self.prev_status: set[str] = set()
        self.remaining = ""       # partie pas encore envoyee de la derniere reponse terminee

    def reset(self) -> None:
        """Fenetre ou liste des messages introuvable."""
        self.pending, self.prev_total = False, None
        self._new_response()

    def _new_response(self) -> None:
        self.spoken = []
        self.spoken_status = set()
        self.prev_paras = []
        self.prev_status = set()

    def _remaining(self, final: list[str]) -> str:
        """Paragraphes de la reponse finale qui n'ont pas deja ete envoyes pendant la generation."""
        spoken = self.spoken
        k = 0
        while k < len(spoken) and k < len(final) and final[k] == spoken[k]:
            k += 1
        if spoken and k < len(spoken):
            # Les textes intermediaires ne sont plus dans la reponse finale (replies) : on repart
            # apres le dernier paragraphe deja lu s'il y est, sinon on lit toute la reponse finale.
            try:
                k = len(final) - final[::-1].index(spoken[-1])
            except ValueError:
                k = 0
        return "\n\n".join(final[k:])

    def feed(self, info: dict, title: str) -> tuple[Optional[str], str]:
        """Renvoie ("partial", morceau), ("read", texte complet), ("load", texte) ou (None, "").

        Apres ("read", ...), `remaining` contient la partie pas encore envoyee en "partial".
        """
        total = info.get("total")
        if title != self.conv:
            # Autre conversation : pas de detection par le nombre de messages, et une reponse
            # "en cours" n'est gardee que pour un nouveau chat (son titre change apres la 1re reponse).
            if not (total is not None and total <= 2):
                self.pending = False
                self._new_response()
            self.prev_total = None
            self.conv = title
        if info["name"].startswith(STREAMING_PREFIX):
            if not self.pending:
                self._new_response()  # nouvelle reponse
            self.pending = True
            chunk = []
            status = info.get("status") or []
            for line in status:
                # Ligne d'etape stable (deja vue au passage precedent) et pas encore lue
                if line in self.prev_status and line not in self.spoken_status:
                    self.spoken_status.add(line)
                    if not is_tool_line(line):
                        chunk.append(line if line[-1] in ".!?…" else line + ".")
            paras = info.get("paragraphs") or []
            done = min(info.get("done_count", 0), len(paras))
            # Paragraphes termines ET identiques au passage precedent (fini de s'afficher)
            stable = 0
            while stable < done and stable < len(self.prev_paras) and paras[stable] == self.prev_paras[stable]:
                stable += 1
            if stable > len(self.spoken):
                new = paras[len(self.spoken):stable]
                self.spoken.extend(new)
                chunk.extend(new)
            self.prev_paras = list(paras)
            self.prev_status = set(status)
            if chunk:
                return "partial", "\n\n".join(chunk)
            return None, ""
        advanced = self.prev_total is not None and total is not None and 0 < total - self.prev_total <= 3
        if total is not None:
            self.prev_total = total
        if not info["claude"]:
            # Message de l'utilisateur, ou reponse de Claude dont l'en-tete "Claude a repondu" n'est
            # pas encore affiche (etat transitoire en fin de generation) : on garde la reponse attendue.
            return None, ""
        if not info["complete"]:
            self.pending = True
            return None, ""
        text = info["text"]
        key = (total, text[:80])
        if not text.strip() or key == self.last_key:
            return None, ""
        self.last_key = key
        if self.pending or advanced:
            self.pending = False
            self.remaining = self._remaining(info.get("paragraphs") or text.split("\n\n"))
            self._new_response()
            return "read", text
        self._new_response()
        return "load", text


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
    """Dans le thread de l'interface : `callback(texte)` quand une reponse vient de se terminer,
    `on_loaded(texte)` quand une conversation est ouverte ou changee (derniere reponse, sans lecture)."""

    _ready = Signal(str, str)  # (reponse complete, partie pas encore envoyee en "partial")
    _loaded = Signal(str)
    _partial = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.callback = None     # callback(texte_complet, reste_a_lire)
        self.on_loaded = None    # on_loaded(texte)
        self.on_partial = None   # on_partial(morceau) : reponse intermediaire terminee
        self._enabled = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ready.connect(self._deliver)  # methode de cet objet : livraison dans le thread de l'interface
        self._loaded.connect(self._deliver_loaded)
        self._partial.connect(self._deliver_partial)

    @property
    def available(self) -> bool:
        return auto is not None

    def _deliver(self, text: str, remaining: str) -> None:
        if self.callback is not None:
            try:
                self.callback(text, remaining)
            except Exception:
                log.exception("Lecture de la reponse Claude Desktop")

    def _deliver_partial(self, text: str) -> None:
        if self.on_partial is not None:
            try:
                self.on_partial(text)
            except Exception:
                log.exception("Lecture d'une reponse intermediaire de Claude Desktop")

    def _deliver_loaded(self, text: str) -> None:
        if self.on_loaded is not None:
            try:
                self.on_loaded(text)
            except Exception:
                log.exception("Chargement de la reponse Claude Desktop")

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
        tracker = ResponseTracker()
        last_state = None
        window_seen = False
        with auto.UIAutomationInitializerInThread():
            while not self._stop.wait(POLL_SECONDS):
                try:
                    win = _find_claude_window()
                    if win is None:
                        if window_seen:
                            log.info("Claude Desktop : fenetre introuvable")
                        window_seen = False
                        tracker.reset()
                        continue
                    if not window_seen:
                        log.info("Claude Desktop : fenetre trouvee")
                        window_seen = True
                    info = _scan(win)
                    if info is None:
                        tracker.reset()
                        continue
                    title = _conversation_title(win)
                    if title != tracker.conv:
                        log.info("Claude Desktop : conversation '%s'", title)
                    state = (info["name"], info["claude"], info["complete"])
                    if state != last_state:
                        log.info("Claude Desktop : %s | Claude=%s | terminee=%s", *state)
                        last_state = state
                    action, text = tracker.feed(info, title)
                    if action == "partial":
                        log.info("Claude Desktop : reponse intermediaire (%d car.)", len(text))
                        self._partial.emit(text)
                    elif action == "read":
                        log.info("Claude Desktop : reponse terminee (%d car., %d pas encore lus)",
                                 len(text), len(tracker.remaining))
                        self._ready.emit(text, tracker.remaining)
                    elif action == "load":
                        log.info("Claude Desktop : derniere reponse chargee (%d car.)", len(text))
                        self._loaded.emit(text)
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
