import ast
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
TESTS = ROOT / "tests"
SRC = ROOT / "src" / "hungry_hunt"


def test_no_real_mailboxes_in_tests():
    hits = [
        p
        for p in TESTS.rglob("*.py")
        if p.name != "test_hygiene.py"
        and re.search(r"(?i)sajjavarapu|sai poojitha|saipoojitha|quantum gandiva", p.read_text())
    ]
    assert hits == []


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_lower_layers_do_not_import_pipeline():
    for rel in ("delivery/digest.py", "discovery/sniff.py", "delivery/send.py", "scoring/assess.py"):
        assert not {m for m in _imports(SRC / rel) if m.startswith("hungry_hunt.pipeline")}, rel
