"""Application au premier plan : sert a griser la barre flottante quand on n'est pas dans Claude Desktop."""
import ctypes
import os
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

CLAUDE_DESKTOP_EXES = frozenset({"claude.exe"})


def foreground_pid() -> int:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def exe_name(pid: int) -> str:
    if not pid:
        return ""
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(h)
    return ""


class FocusTracker:
    """Dit si la barre doit etre active d'apres l'appli au premier plan.

    - une appli de `active_exes` au premier plan (Claude Desktop) -> active ;
    - toute autre appli -> grisee ;
    - nos propres fenetres (barre, options, fenetre texte) ou aucune fenetre -> etat garde,
      pour que cliquer sur la barre ne la grise pas.
    """

    def __init__(self, active_exes=CLAUDE_DESKTOP_EXES, initial: bool = True):
        self.active_exes = frozenset(e.lower() for e in active_exes)
        self.active = bool(initial)
        self._own_pid = os.getpid()
        self._last_pid = None

    def update(self) -> bool:
        try:
            pid = foreground_pid()
        except Exception:
            return self.active
        if not pid or pid == self._own_pid or pid == self._last_pid:
            return self.active
        self._last_pid = pid
        self.active = exe_name(pid) in self.active_exes
        return self.active
