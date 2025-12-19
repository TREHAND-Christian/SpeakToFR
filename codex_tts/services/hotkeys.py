"""Gestion du raccourci global et du vrai Ctrl+C via AutoHotkey."""
import time
import subprocess
import ctypes
import os
from ctypes import wintypes

import win32con

from codex_tts.services.clipboard import get_clipboard_text, set_clipboard_text
from codex_tts.core.config import TAG, HOTKEY_ID, MOD_CTRL_ALT, VK_ENTER, AHK_PATH, AHK_EXE

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
RegisterHotKey = user32.RegisterHotKey
UnregisterHotKey = user32.UnregisterHotKey

HOTKEY_THREAD_ID = None


def stop_hotkey_loop():
    """Demande proprement l'arret du thread hotkey (WM_QUIT)."""
    tid = HOTKEY_THREAD_ID
    if not tid:
        return
    try:
        user32.PostThreadMessageW(tid, win32con.WM_QUIT, 0, 0)
    except Exception:
        pass


def release_hotkey_modifiers():
    """
    WM_HOTKEY arrive alors que Ctrl/Alt sont encore appuyés.
    Si on envoie Ctrl+C tout de suite, ça devient souvent Ctrl+Alt+C.
    => On force un relâchement de Ctrl/Alt avant la copie.
    """
    for vk in (
        win32con.VK_LCONTROL, win32con.VK_RCONTROL, win32con.VK_CONTROL,
        win32con.VK_LMENU, win32con.VK_RMENU, win32con.VK_MENU
    ):
        try:
            user32.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        except Exception:
            pass


def real_ctrl_c():
    """
    1) Préfère AutoHotkey (si présent)
    2) Sinon fallback via keybd_event
    """
    try:
        if os.path.exists(AHK_EXE) and os.path.exists(AHK_PATH):
            subprocess.Popen([AHK_EXE, AHK_PATH])
            return
    except Exception:
        pass

    # Fallback : simulate Ctrl+C
    try:
        user32.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        user32.keybd_event(ord('C'), 0, 0, 0)
        user32.keybd_event(ord('C'), 0, win32con.KEYEVENTF_KEYUP, 0)
        user32.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


def hotkey_loop():
    global HOTKEY_THREAD_ID
    ok = RegisterHotKey(None, HOTKEY_ID, MOD_CTRL_ALT, VK_ENTER)
    if not ok:
        print("[CodexTTS] ERREUR : impossible d'enregistrer Ctrl+Alt+Entrée.")
        try:
            user32.MessageBoxW(
                None,
                "Impossible d'activer le raccourci global Ctrl+Alt+Entrée.\n"
                "Verifiez qu'aucune autre application ne l'utilise et que vous avez les droits necessaires.",
                "CodexTTS",
                win32con.MB_ICONERROR | win32con.MB_OK,
            )
        except Exception:
            pass
        return

    try:
        HOTKEY_THREAD_ID = kernel32.GetCurrentThreadId()
    except Exception:
        HOTKEY_THREAD_ID = None
    print("[CodexTTS] Raccourci actif : Ctrl + Alt + Entree")

    msg = wintypes.MSG()

    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret == 0:
            break
        if ret == -1:
            print("[CodexTTS] ERREUR : GetMessageW a echoue.")
            break

        if msg.message == win32con.WM_HOTKEY and msg.wParam == HOTKEY_ID:
            print("[CodexTTS] Hotkey detecte, copie le texte.")

            before = get_clipboard_text()

            # IMPORTANT : éviter Ctrl+Alt+C
            release_hotkey_modifiers()
            time.sleep(0.03)

            real_ctrl_c()

            # Attendre un vrai changement du presse-papiers
            new = ""
            for _ in range(30):  # ~1.5s max
                time.sleep(0.05)
                cur = get_clipboard_text()
                if cur != before:
                    new = cur
                    break

            if new.strip():
                tagged = f"{TAG}\n{new}"
            else:
                tagged = f"{TAG}\nveuillez selectionner un texte"

            ok = set_clipboard_text(tagged)
            if ok:
                print("[CodexTTS] Texte balise dans le presse-papiers.")
            else:
                print("[CodexTTS] Impossible d'ecrire dans le presse-papiers (verrouille ?).")

        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    UnregisterHotKey(None, HOTKEY_ID)
    HOTKEY_THREAD_ID = None
