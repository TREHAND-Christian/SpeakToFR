"""Zone texte en rendu fidele : la selection est affichee par le moteur Chromium de Qt (QtWebEngine).

- Les scripts de la page ne s'executent pas (JavaScript desactive pour la page, scripts retires
  du HTML) ; nos fonctions (surlignage, cartes, mesure) tournent dans un monde JavaScript isole.
- Un clic sur un lien l'ouvre dans le navigateur par defaut (la vue ne quitte jamais le texte).
- Le surlignage de la phrase lue utilise l'API CSS Highlight : le HTML n'est pas modifie.
- Les cartes (blocs voisins de meme classe, chacun avec une image) sont remises cote a cote :
  la copie du navigateur ne contient pas la mise en page (grid/flex) des feuilles de style.

Qt WebEngine doit etre initialise avant la creation de QApplication : init_web_engine() est
appele par main.py. Sans cet appel (tests, environnement sans WebEngine), le rendu simplifie
(QTextEdit) est utilise.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from typing import Optional

from PySide6.QtCore import QCoreApplication, Qt, QTimer, QUrl

from ..core.prefs import load_prefs
from ..text.web_align import js_ignored_class

log = logging.getLogger(__name__)

_READY = False
_CLASSES = None
# setHtml passe par une URL data: limitee a 2 Mo : au-dela, la page est ecrite dans un fichier
_SETHTML_LIMIT = 1_500_000

_HELPER_JS = r"""
(function () {
  if (window.__stfr) return;
  var IGN = /%IGN%/;
  var map = null;

  function build() {
    var nodes = [], ni = [], of = [], parts = [];
    var root = document.body || document.documentElement;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var n;
    while ((n = w.nextNode())) {
      var p = n.parentElement;
      if (!p || p.closest('script,style,noscript,template,svg,title,head')) continue;
      var t = n.data, k = nodes.length;
      nodes.push(n);
      for (var i = 0; i < t.length; i++) {
        var c = t.charAt(i);
        if (IGN.test(c)) continue;
        parts.push(c); ni.push(k); of.push(i);
      }
    }
    map = { g: parts.join(''), nodes: nodes, ni: ni, of: of };
  }

  function locate(ns, ne, key) {
    if (!map) build();
    var g = map.g, len = ne - ns;
    if (len <= 0 || !g.length) return null;
    var s = ns;
    if (key && g.substr(ns, key.length) !== key) {
      // Les deux textes divergent un peu : on recale sur l'occurrence de la cle la plus proche
      var best = -1, bestD = 1e15, i = g.indexOf(key);
      while (i !== -1) {
        var d = Math.abs(i - ns);
        if (d < bestD) { bestD = d; best = i; }
        if (i > ns) break;
        i = g.indexOf(key, i + 1);
      }
      if (best >= 0) s = best;
    }
    s = Math.max(0, Math.min(s, g.length - 1));
    var e = Math.min(g.length, s + len);
    var r = document.createRange();
    r.setStart(map.nodes[map.ni[s]], map.of[s]);
    r.setEnd(map.nodes[map.ni[e - 1]], map.of[e - 1] + 1);
    return r;
  }

  function clear() {
    if (window.CSS && CSS.highlights) CSS.highlights.delete('stfr');
    else { var sel = getSelection(); if (sel) sel.removeAllRanges(); }
  }

  function highlight(segs) {
    var ranges = [];
    for (var i = 0; i < segs.length; i++) {
      var r = locate(segs[i][0], segs[i][1], segs[i][2]);
      if (r) ranges.push(r);
    }
    clear();
    if (!ranges.length) return 0;
    if (window.CSS && CSS.highlights && window.Highlight) {
      var h = new Highlight();
      ranges.forEach(function (x) { h.add(x); });
      CSS.highlights.set('stfr', h);
    } else {
      var sel = getSelection();
      ranges.forEach(function (x) { sel.addRange(x); });
    }
    var rect = ranges[0].getBoundingClientRect(), vh = window.innerHeight;
    if (rect.top < 0 || rect.bottom > vh) window.scrollBy(0, rect.top - vh * 0.3);
    return ranges.length;
  }

  function imgWidth(img, natural) {
    var sw = img.style.width || '';
    if (/px$/.test(sw) && parseFloat(sw)) return parseFloat(sw);
    var a = parseFloat(img.getAttribute('width') || '');
    if (a) return a;
    if (natural && img.naturalWidth) return Math.min(img.naturalWidth, 420);
    return 0;
  }

  function cardImage(el, natural) {
    var best = 0, imgs = el.querySelectorAll('img');
    for (var i = 0; i < imgs.length; i++) best = Math.max(best, imgWidth(imgs[i], natural));
    if (!best) {
      var bgs = el.querySelectorAll('[style*="url("]');
      for (var j = 0; j < bgs.length; j++) {
        var bw = bgs[j].style.width || '';
        best = Math.max(best, /px$/.test(bw) ? parseFloat(bw) : 0);
      }
    }
    return best;
  }

  function cards(natural) {
    var body = document.body;
    if (!body) return 0;
    var list = [body].concat(Array.prototype.slice.call(body.querySelectorAll('*')));
    var done = 0;
    for (var pi = 0; pi < list.length; pi++) {
      var P = list[pi];
      if (P.__stfrCards || P.closest('[data-stfr-card]') || P.closest('svg')) continue;
      var kids = P.children;
      if (kids.length < 2) continue;
      var disp = getComputedStyle(P).display;
      if (disp.indexOf('flex') >= 0 || disp.indexOf('grid') >= 0 || disp.indexOf('inline') === 0 ||
          disp.indexOf('table') === 0) continue;
      var groups = {}, best = null;
      for (var k = 0; k < kids.length; k++) {
        var K = kids[k];
        if (/^(IMG|BR|HR|SCRIPT|STYLE)$/.test(K.tagName)) continue;
        var cls = ((K.getAttribute('class') || '').trim().split(/\s+/)[0]) || '';
        var key = K.tagName + '.' + cls;
        (groups[key] = groups[key] || []).push(K);
      }
      for (var g in groups) {
        if (groups[g].length >= 2 && (!best || groups[g].length > best.length)) best = groups[g];
      }
      if (!best) continue;
      var widths = [], ok = true;
      for (var b = 0; b < best.length; b++) {
        var kd = getComputedStyle(best[b]).display;
        if (kd.indexOf('inline') === 0 || (best[b].textContent || '').trim().length > 500) { ok = false; break; }
        var w = cardImage(best[b], natural);
        if (w >= 80) widths.push(w);
      }
      if (!ok || widths.length < Math.ceil(best.length * 0.6)) continue;
      var cw = Math.max(160, Math.min(420, Math.max.apply(null, widths)));
      P.style.display = 'flex';
      P.style.flexWrap = 'wrap';
      P.style.gap = '12px';
      P.style.alignItems = 'stretch';
      for (var c = 0; c < kids.length; c++) {
        var C = kids[c];
        if (best.indexOf(C) >= 0) {
          C.style.flex = '0 0 ' + cw + 'px';
          C.style.width = cw + 'px';
          C.style.maxWidth = '100%';
          C.style.boxSizing = 'border-box';
          C.setAttribute('data-stfr-card', '1');
        } else {
          C.style.flexBasis = '100%';
        }
      }
      P.__stfrCards = true;
      done++;
    }
    return done;
  }

  function size() {
    var d = document.documentElement, b = document.body;
    return [Math.max(d.scrollHeight, b ? b.scrollHeight : 0), Math.max(d.scrollWidth, b ? b.scrollWidth : 0)];
  }

  window.__stfr = { highlight: highlight, clear: clear, cards: cards, size: size };
  try { cards(false); } catch (e) {}
})();
"""


def init_web_engine() -> bool:
    """A appeler avant la creation de QApplication (exigence de Qt WebEngine)."""
    global _READY
    if _READY:
        return True
    try:
        if QCoreApplication.instance() is not None:
            log.warning("Qt WebEngine : QApplication deja creee, rendu fidele desactive")
            return False
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        import PySide6.QtWebEngineCore  # noqa: F401
        import PySide6.QtWebEngineWidgets  # noqa: F401

        _READY = True
    except Exception:
        log.exception("Qt WebEngine indisponible : rendu simplifie seulement")
        _READY = False
    return _READY


def web_available() -> bool:
    return _READY


def faithful_render_enabled() -> bool:
    """Rendu fidele (Chromium) si disponible et si l'option est cochee (par defaut : oui)."""
    if not _READY:
        return False
    prefs = load_prefs() or {}
    return bool(prefs.get("text_render_faithful", True))


def _qcolor(css: str):
    from PySide6.QtGui import QColor

    m = re.match(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", css or "")
    return QColor(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else QColor("white")


def _classes():
    global _CLASSES
    if _CLASSES is not None:
        return _CLASSES

    from PySide6.QtCore import Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QMenu

    world = int(QWebEngineScript.ScriptWorldId.ApplicationWorld.value)

    class _Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            nt = QWebEnginePage.NavigationType
            if nav_type == nt.NavigationTypeLinkClicked:
                if url.scheme() in ("http", "https", "mailto"):
                    QDesktopServices.openUrl(url)
                return False
            if nav_type == nt.NavigationTypeFormSubmitted:
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def createWindow(self, _type):
            return None

        def javaScriptConsoleMessage(self, level, message, line, source):
            log.debug("web: %s (%s:%s)", message, source, line)

    class TextWebView(QWebEngineView):
        """Vue Chromium de la fenetre texte (voir le module)."""

        content_size_changed = Signal(int, int)

        def __init__(self, parent=None):
            super().__init__(parent)
            page = _Page(self)
            self.setPage(page)
            s = page.settings()
            wa = QWebEngineSettings.WebAttribute
            for attr, on in (
                (wa.JavascriptEnabled, False),
                (wa.JavascriptCanOpenWindows, False),
                (wa.PluginsEnabled, False),
                (wa.ErrorPageEnabled, False),
                (wa.LocalContentCanAccessRemoteUrls, True),
                (wa.AutoLoadImages, True),
                (wa.ScrollAnimatorEnabled, False),
                (wa.FocusOnNavigationEnabled, False),
            ):
                try:
                    s.setAttribute(attr, on)
                except Exception:
                    pass
            script = QWebEngineScript()
            script.setName("speaktofr")
            script.setSourceCode(_HELPER_JS.replace("%IGN%", js_ignored_class()))
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            script.setWorldId(world)
            script.setRunsOnSubFrames(False)
            page.scripts().insert(script)

            self.setAcceptDrops(False)
            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self._menu)
            self.loadFinished.connect(self._on_loaded)
            self._html: Optional[str] = None
            self._loaded = False
            self._pending = None
            self._tmp: Optional[str] = None

        # ---------------------------------------------------------- contenu
        def show_html(self, doc: str, base_url: Optional[str], bg_css: str) -> bool:
            """Charge la page ; False si elle est deja affichee (relance : pas de rechargement)."""
            if doc == self._html:
                return False
            self._html = doc
            self._loaded = False
            self._pending = None
            self.page().setBackgroundColor(_qcolor(bg_css))
            base = QUrl(base_url) if base_url and base_url.lower().startswith(("http://", "https://")) else QUrl()
            data = doc.encode("utf-8")
            self._drop_tmp()
            if len(data) <= _SETHTML_LIMIT:
                self.setHtml(doc, base)
            else:
                fd, path = tempfile.mkstemp(prefix="speaktofr_", suffix=".html")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                self._tmp = path
                self.load(QUrl.fromLocalFile(path))
            return True

        def _drop_tmp(self) -> None:
            if self._tmp:
                try:
                    os.remove(self._tmp)
                except OSError:
                    pass
                self._tmp = None

        def _run(self, expr: str, callback=None) -> None:
            js = "(function(){ if (!window.__stfr) return null; return %s; })()" % expr
            if callback is None:
                self.page().runJavaScript(js, world)
            else:
                self.page().runJavaScript(js, world, callback)

        def _on_loaded(self, ok: bool) -> None:
            self._loaded = True
            # Images chargees : leur taille reelle permet de reconnaitre d'autres cartes
            self._run("__stfr.cards(true)")
            if self._pending is not None:
                segs, self._pending = self._pending, None
                self.highlight(segs)
            self._measure()
            QTimer.singleShot(700, self._measure)

        def _measure(self) -> None:
            def got(res):
                # PySide6 ne convertit pas les tableaux JavaScript : resultat en JSON
                try:
                    h, w = json.loads(res) if isinstance(res, str) and res else (0, 0)
                    if h:
                        self.content_size_changed.emit(int(h), int(w))
                except (ValueError, TypeError, RuntimeError):  # JSON invalide ou vue detruite
                    pass

            if self._loaded:
                self._run("JSON.stringify(__stfr.size())", got)

        # ------------------------------------------------------- surlignage
        def highlight(self, segments: list) -> None:
            """segments : [[debut_visible, fin_visible, cle], ...] (voir text.web_align)."""
            if not self._loaded:
                self._pending = segments
                return
            self._run("__stfr.highlight(%s)" % json.dumps(segments))

        def clear_highlight(self) -> None:
            self._pending = None
            if self._loaded:
                self._run("__stfr.clear()")

        # ---------------------------------------------------------- divers
        def _menu(self, pos) -> None:
            menu = QMenu(self)
            act_copy = menu.addAction("Copier")
            act_all = menu.addAction("Tout sélectionner")
            act_copy.setEnabled(self.page().hasSelection())
            chosen = menu.exec(self.mapToGlobal(pos))
            if chosen is act_copy:
                self.page().triggerAction(QWebEnginePage.WebAction.Copy)
            elif chosen is act_all:
                self.page().triggerAction(QWebEnginePage.WebAction.SelectAll)

        def closeEvent(self, event):
            self._drop_tmp()
            super().closeEvent(event)

        def __del__(self):
            try:
                self._drop_tmp()
            except Exception:
                pass

    _CLASSES = TextWebView
    return _CLASSES


def create_web_view(parent=None):
    """Nouvelle vue Chromium pour la fenetre texte (init_web_engine() doit avoir reussi)."""
    if not _READY:
        raise RuntimeError("Qt WebEngine non initialise")
    return _classes()(parent)
