import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"


def test_index_served_after_login(logged_in_client):
    res = logged_in_client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_index_redirects_when_anonymous(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/login"


def test_login_redirects_when_already_signed_in(logged_in_client):
    res = logged_in_client.get("/login", follow_redirects=False)
    assert res.status_code == 303


def test_static_assets_served_to_session(logged_in_client):
    for path in ("/static/js/main.js", "/static/js/views/opportunities.js",
                 "/static/js/mascot-sprites.js", "/static/css/tokens.css"):
        assert logged_in_client.get(path).status_code == 200, path
    assert logged_in_client.get("/static/js/legacy.js").status_code == 404


def test_pages_are_csp_clean():
    """No inline <style>, style=, inline <script> or on* handlers (CSP: 'self' only)."""
    for page in STATIC.glob("*.html"):
        html = page.read_text()
        assert not re.search(r"<style[\s>]", html), page.name
        assert not re.search(r"\sstyle\s*=", html), page.name
        assert not re.search(r"\son[a-z]+\s*=", html), page.name
        for m in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S):
            assert "src=" in m.group(1) and not m.group(2).strip(), page.name


def test_js_has_no_inline_style_attributes():
    for js in STATIC.rglob("*.js"):
        text = js.read_text()
        assert not re.search(r"""\sstyle\s*=\s*["']""", text), js.name
        assert not re.search(r"""\son(click|change|input|submit)\s*=""", text), js.name


def test_js_modules_are_private_but_css_is_public(client):
    assert client.get("/static/css/tokens.css").status_code == 200
    assert client.get("/static/js/main.js", follow_redirects=False).status_code in (303, 401)


def test_no_innerhtml_in_ui_code():
    """Market titles, rules and model text must only ever be set as text."""
    for js in (STATIC / "js").rglob("*.js"):
        text = js.read_text()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert bad not in text, f"{js.name} uses {bad}"


def test_mascot_sprites_are_24x24_and_cover_every_state():
    import json
    import re
    text = (STATIC / "js" / "mascot-sprites.js").read_text()
    body = text[text.index("export const SPRITES"):]
    frames = {}
    for name in ("idle", "scanning", "verifying", "analysing", "found", "error", "offline"):
        m = re.search(rf"\n  {name}: \[\n(.*?)\n  \],", body, re.S)
        assert m, name
        rows = re.findall(r'"([^"]*)"', m.group(1))
        assert len(rows) % 24 == 0 and all(len(r) == 24 for r in rows), name
        frames[name] = len(rows) // 24
    assert frames == {"idle": 2, "scanning": 4, "verifying": 3, "analysing": 3,
                      "found": 2, "error": 1, "offline": 1}


def test_tokens_define_both_themes():
    css = (STATIC / "css" / "tokens.css").read_text()
    assert "prefers-color-scheme: dark" in css and ':root[data-theme="dark"]' in css
    for token in ("--bg", "--ink", "--accent", "--rule", "--muted"):
        assert css.count(f"{token}:") >= 3        # light, dark media block, dark attribute block
