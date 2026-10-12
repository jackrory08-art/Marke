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
    assert logged_in_client.get("/static/js/legacy.js").status_code == 200
    assert logged_in_client.get("/static/css/legacy.css").status_code == 200


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
