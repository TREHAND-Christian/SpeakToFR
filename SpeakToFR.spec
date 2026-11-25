# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('help.html', '.')],
    hiddenimports=['uiautomation', 'comtypes', 'comtypes.client'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------- allegement
# Qt WebEngine entraine tout Qt Quick/QML (3D, graphiques, cartes...) dont la fenetre texte
# n'a pas besoin, des ressources de debug et toutes les langues. On ne garde que l'utile.
import os
import re

from PyInstaller.depend.bindepend import get_imports


def _norm(p):
    return p.replace('/', '\\').lower()


def _keep_file(dest):
    d = _norm(dest)
    name = os.path.basename(d)
    if d.startswith('pyside6\\qml\\'):
        return False
    if d.startswith('pyside6\\resources\\') and '.debug.' in name:
        return False
    if d.startswith('pyside6\\translations\\'):
        if 'qtwebengine_locales' in d:
            return name in ('fr.pak', 'en-us.pak')
        return name.endswith(('_fr.qm', '_en.qm'))
    return True


a.datas = [x for x in a.datas if _keep_file(x[0])]
a.binaries = [x for x in a.binaries if _keep_file(x[0])]

# DLL Qt6*.dll gardees seulement si un module/plugin/exe conserve en depend (directement ou non)
_QT_DLL = re.compile(r'^pyside6\\qt6[^\\]+\.dll$')
_qt = {os.path.basename(_norm(b[0])): b[1] for b in a.binaries if _QT_DLL.match(_norm(b[0]))}
_stack = [b[1] for b in a.binaries if not _QT_DLL.match(_norm(b[0]))]
_seen, _needed = set(), set()
while _stack:
    _path = _stack.pop()
    if _path in _seen:
        continue
    _seen.add(_path)
    try:
        _imports = get_imports(_path)
    except Exception:
        continue
    for _imp in _imports:
        _name = os.path.basename(_imp[0] if isinstance(_imp, (tuple, list)) else str(_imp)).lower()
        if _name in _qt and _name not in _needed:
            _needed.add(_name)
            _stack.append(_qt[_name])
_dropped = sorted(n for n in _qt if n not in _needed)
print('SpeakToFR: DLL Qt retirees :', ', '.join(_dropped) or 'aucune')
a.binaries = [b for b in a.binaries
              if not _QT_DLL.match(_norm(b[0])) or os.path.basename(_norm(b[0])) in _needed]

pyz = PYZ(a.pure)

# Dossier (onedir) et non exe unique : Qt WebEngine (rendu fidele de la fenetre texte) pese
# ~200 Mo, un exe unique le decompresserait dans %TEMP% a chaque lancement.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SpeakToFR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SpeakToFR',
)
