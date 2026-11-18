#!/usr/bin/env python3
"""Map a repository into graphify-out/GRAPH_REPORT.md using only the standard library.

Scans Python AST imports and class definitions, TypeScript/JavaScript import
specifiers, SQLAlchemy-style models, and CREATE TABLE statements.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    "graphify-out",
    ".jedoc",
    ".cursor",
}
PY_SKIP_SUFFIX = {".pyc"}
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql"}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in CODE_EXT:
            yield path


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def scan_python(path: Path) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"imports": [], "classes": [], "functions": [], "tables": [], "error": str(exc)}
    imports: list[str] = []
    classes: list[str] = []
    functions: list[str] = []
    tables: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            imports.append(base)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
            if any(name in {"Base", "DeclarativeBase", "Model"} for name in bases):
                table_name = None
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name) and target.id == "__tablename__":
                                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                    table_name = stmt.value.value
                tables.append(table_name or node.name)
        elif isinstance(node, ast.FunctionDef) and isinstance(getattr(node, "col_offset", 0), int):
            if node.col_offset == 0:
                functions.append(node.name)
    return {"imports": imports, "classes": classes, "functions": functions[:40], "tables": tables, "error": ""}


IMPORT_RE = re.compile(
    r"""(?:import\s+(?:type\s+)?(?:[\w*\s{},]+\s+from\s+)?|export\s+.+?\s+from\s+)['"]([^'"]+)['"]"""
)
CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\[]?\w+[`\"\]]?)", re.I)


def scan_script(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    imports = IMPORT_RE.findall(text)
    tables = [name.strip('`"[]') for name in CREATE_TABLE_RE.findall(text)]
    return {"imports": imports, "classes": [], "functions": [], "tables": tables, "error": ""}


def scan_sql(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    tables = [name.strip('`"[]') for name in CREATE_TABLE_RE.findall(text)]
    return {"imports": [], "classes": [], "functions": [], "tables": tables, "error": ""}


def mermaid_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "m_" + cleaned
    return cleaned[:80]


def build_report(root: Path) -> str:
    modules: dict[str, dict] = {}
    inbound: dict[str, set[str]] = defaultdict(set)
    for path in sorted(iter_files(root)):
        key = rel(root, path)
        if path.suffix == ".py":
            info = scan_python(path)
        elif path.suffix == ".sql":
            info = scan_sql(path)
        else:
            info = scan_script(path)
        modules[key] = info

    py_modules = {key[:-3].replace("/", ".") for key in modules if key.endswith(".py")}
    for key, info in modules.items():
        for imp in info["imports"]:
            target = imp.strip(".")
            if target in py_modules or any(target.startswith(mod + ".") or mod.startswith(target) for mod in py_modules):
                match = next((mod for mod in py_modules if mod == target or target.startswith(mod + ".") or mod.startswith(target)), None)
                if match:
                    inbound[match].add(key)

    lines = [
        "# Graph report",
        "",
        f"Root: `{root}`",
        "",
        f"Scanned {len(modules)} source files.",
        "",
        "## Modules",
        "",
    ]
    for key, info in modules.items():
        bits = []
        if info["classes"]:
            bits.append("classes: " + ", ".join(info["classes"][:12]))
        if info["tables"]:
            bits.append("tables: " + ", ".join(info["tables"]))
        if info["imports"]:
            bits.append("imports: " + ", ".join(info["imports"][:12]))
        if info["error"]:
            bits.append("parse error: " + info["error"])
        detail = "; ".join(bits) if bits else "no structural symbols"
        lines.append(f"- `{key}` — {detail}")

    lines.extend(["", "## Tables", ""])
    tables = []
    for key, info in modules.items():
        for table in info["tables"]:
            tables.append((table, key))
    if not tables:
        lines.append("No SQLAlchemy models or CREATE TABLE statements found.")
    else:
        for table, key in tables:
            lines.append(f"- `{table}` declared in `{key}`")

    lines.extend(["", "## Import sketch", "", "```mermaid", "flowchart LR"])
    shown = 0
    for key, info in modules.items():
        if shown >= 40:
            break
        if not info["imports"]:
            continue
        src = mermaid_id(key)
        lines.append(f"  {src}[\"{key}\"]")
        for imp in info["imports"][:6]:
            dst = mermaid_id(imp)
            lines.append(f"  {src} --> {dst}[\"{imp}\"]")
            shown += 1
    if shown == 0:
        lines.append("  empty[\"no imports discovered\"]")
    lines.extend(["```", "", "## Notes", "", "- Dynamic imports, runtime registries, and generated code are invisible to this scan.", "- Re-run after structural edits.", ""])
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    out_dir = root / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(root)
    dest = out_dir / "GRAPH_REPORT.md"
    dest.write_text(report, encoding="utf-8")
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
