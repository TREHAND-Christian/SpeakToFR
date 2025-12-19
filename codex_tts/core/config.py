"""Configuration globale de CodexTTS (touches, tag, chemins AHK)."""
import ctypes
import win32con

TAG = "[CODEX_TTS]"

# Hotkey global : Ctrl + Alt + Enter
HOTKEY_ID = 1
MOD_CTRL_ALT = win32con.MOD_CONTROL | win32con.MOD_ALT
VK_ENTER = win32con.VK_RETURN

# Scripts AutoHotkey (v2)
AHK_PATH = r"C:\Program Files\CodexTTS\copy_real.ahk"
AHK_EXE = r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
