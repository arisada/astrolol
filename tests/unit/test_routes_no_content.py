"""Routes answering 204 declare response_model=None.

FastAPI 0.115 (Debian 13) takes a `-> None` return annotation for a response
model and refuses to register a 204 route with one; newer versions accept it, so nothing else in
development would notice.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "astrolol"


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def test_204_routes_have_no_response_model() -> None:
    offenders = []
    for path in ROOT.rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                status = _keyword(deco, "status_code")
                if not (isinstance(status, ast.Constant) and status.value == 204):
                    continue
                model = _keyword(deco, "response_model")
                if not (isinstance(model, ast.Constant) and model.value is None):
                    offenders.append(f"{path.relative_to(ROOT.parent)}:{deco.lineno} {node.name}")
    assert not offenders, "status_code=204 without response_model=None:\n" + "\n".join(offenders)
