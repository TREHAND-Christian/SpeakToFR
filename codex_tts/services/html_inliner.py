"""Inlining HTML via Chromium (Playwright) + getComputedStyle.

Objectif: obtenir un fragment HTML autonome (styles inline) sans dépendre de feuilles CSS dans l'app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class InlineResult:
    ok: bool
    html: str
    error: Optional[str] = None


_INLINE_JS = r"""
(html) => {
  // Injecte le fragment dans un conteneur isolé
  const container = document.createElement('div');
  container.setAttribute('data-speaktofr-root', '1');
  container.innerHTML = html;

  // On prend le premier élément (ou le conteneur si texte)
  let root = container.firstElementChild || container;

  // Clone pour ne pas modifier l'original
  const clone = root.cloneNode(true);

  const origNodes = [root, ...root.querySelectorAll("*")];
  const cloneNodes = [clone, ...clone.querySelectorAll("*")];

  for (let i = 0; i < origNodes.length; i++) {
    const o = origNodes[i];
    const c = cloneNodes[i];
    const cs = getComputedStyle(o);
    let style = "";
    for (let j = 0; j < cs.length; j++) {
      const prop = cs[j];
      style += `${prop}:${cs.getPropertyValue(prop)};`;
    }
    c.setAttribute("style", style);
  }
  return clone.outerHTML;
}
"""


def inline_html_with_computed_styles(
    source_url: str,
    html_fragment: str,
    *,
    timeout_ms: int = 15000,
    remove_images: bool = True,
    headless: bool = True,
) -> InlineResult:
    """Charge source_url dans Chromium headless, injecte le fragment, puis inline les styles calculés.

    - Si Playwright/Chromium n'est pas dispo, renvoie ok=False.
    - Ne modifie pas html_fragment en dehors du style inline (optionnellement supprime <img>).
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return InlineResult(False, html_fragment, f"Playwright non dispo: {e}")

    if not source_url:
        return InlineResult(False, html_fragment, "source_url vide")

    html_in = html_fragment or ""
    if remove_images:
        # léger: vire les img (souhait récurrent côté SpeakToFR)
        import re
        html_in = re.sub(r"<img\b[^>]*>", "", html_in, flags=re.I)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            page.goto(source_url, wait_until="networkidle", timeout=timeout_ms)
            # Important: on injecte le fragment dans la page chargée (pour bénéficier de ses CSS)
            out = page.evaluate(_INLINE_JS, html_in)
            browser.close()
        if isinstance(out, str) and out.strip():
            return InlineResult(True, out)
        return InlineResult(False, html_fragment, "Résultat vide")
    except Exception as e:
        return InlineResult(False, html_fragment, str(e))
