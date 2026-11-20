"""Mise en forme des blocs <pre>/<code> pour l'affichage Qt."""
import html
import re


def style_pre_blocks(html_fragment: str) -> str:
    """
    Force un rendu lisible des blocs <pre> dans QTextEdit (Qt) :
    - fond noir
    - texte blanc
    - padding + police monospace
    IMPORTANT : Qt applique beaucoup mieux le style INLINE que <style>...</style>.
    """
    if not html_fragment:
        return html_fragment


    # Extrait head/body s'ils existent (sans toucher au contenu head)
    body = html_fragment
    head_content = ""
    m_body = re.search(r"<body[^>]*>(.*)</body>", html_fragment, flags=re.IGNORECASE | re.DOTALL)
    if m_body:
        body = m_body.group(1)
    m_head = re.search(r"<head[^>]*>(.*)</head>", html_fragment, flags=re.IGNORECASE | re.DOTALL)
    if m_head:
        head_content = m_head.group(1)

    def _strip_attrs(tag_match):
        tag = tag_match.group(1)
        # Conserve les balises sans attributs (on ne garde pas les attrs)
        return f"<{tag}>"


    def _process_pre(match):
        inner = match.group(1) or ""

        # 1) Convertit le contenu du <pre> en TEXTE BRUT (Qt déteste les <span>/<div> cassés dedans)
        #    On enlève toutes les balises (ouvrantes ET fermantes).
        text = re.sub(r"</?[^>]+>", "", inner)

        # 2) Normalise les retours ligne
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 3) Tabulations -> 4 espaces (ajuste si tu préfères 2/8)
        text = text.replace("\t", "    ")

        # 4) Décodage des entités puis ré-échappement (affichage fidèle du code)
        text = html.unescape(text)
        text = (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

        # 5) Prépare chaque ligne : indentation préservée (espaces de début -> &nbsp;)
        lines = text.split("\n")
        fixed_lines = []
        for line in lines:
            # compte les espaces en début de ligne
            leading = len(line) - len(line.lstrip(" "))
            if leading:
                line = ("&nbsp;" * leading) + line[leading:]
            # IMPORTANT: une ligne vide doit rester visible => &nbsp;
            if line == "":
                line = "&nbsp;"
            fixed_lines.append(line)

        inner_html = "<br/>".join(fixed_lines)

        # Style INLINE (fiable dans Qt)
        pre_style = (
            "background:#000 !important;"
            "color:#fff !important;"
            "padding:6px 8px !important;"
            "display:block !important;"
            "border-radius:4px !important;"
            "font-family:monospace !important;"
            # On gère nous-mêmes les retours/espaces avec <br/> et &nbsp;
            "white-space:normal !important;"
        )

        # Force la couleur à l'intérieur (héritage parfois foireux dans Qt)
        inner_html = f'<span style="color:#fff !important;">{inner_html}</span>'

        return f'<pre style="{pre_style}">{inner_html}</pre>'

    # Remplace tous les <pre ...>...</pre> par des <pre style="...">...</pre>
    pre_blocks = []

    def _replace_pre(match):
        processed = _process_pre(match)
        pre_blocks.append(processed)
        return f"__PRE_BLOCK_{len(pre_blocks) - 1}__"

    body = re.sub(r"<pre[^>]*>(.*?)</pre>", _replace_pre, body, flags=re.IGNORECASE | re.DOTALL)

    # Ajoute un style lisible aux balises <code> (hors <pre>)
    code_style = "background:#f2f2f2 !important;padding:1px 4px !important;border-radius:3px !important;font-family:monospace !important;"

    def _style_code(match):
        attrs = match.group(1) or ""
        if "style=" in attrs.lower():
            return match.group(0).replace("style=", f'style="{code_style}', 1)
        sep = "" if attrs.strip().endswith("/") or not attrs.strip() else " "
        return f"<code{attrs}{sep}style=\"{code_style}\">"

    body = re.sub(r"<code([^>]*)>", _style_code, body, flags=re.IGNORECASE)

    # Restaure les blocs <pre> deja stylises
    for idx, pre_html in enumerate(pre_blocks):
        body = body.replace(f"__PRE_BLOCK_{idx}__", pre_html)

    return f"<html><head>{head_content}</head><body>{body}</body></html>"
