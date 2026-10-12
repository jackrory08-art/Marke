import subprocess
import sys

HEAVY = ["sqlalchemy", "alembic", "argon2", "google.genai", "fastapi"]


def run(code: str) -> str:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_main_imports_no_web_db_or_ai_packages():
    out = run("import sys, main; print(','.join(m for m in %r if m in sys.modules))" % HEAVY)
    assert out == ""


def test_config_and_core_import_without_ai_or_db():
    out = run("import sys, utils.config_loader, core.cross_platform_arb, core.fees; "
              "print(','.join(m for m in %r if m in sys.modules))" % HEAVY)
    assert out == ""
