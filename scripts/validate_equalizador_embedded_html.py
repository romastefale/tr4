#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
from html.parser import HTMLParser
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HTML_CONSTANTS = ("_EQUALIZADOR_HTML", "_PUBLIC_MUSIC_HTML")
SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.IGNORECASE | re.DOTALL)
ID_RE = re.compile(r"\bid\s*=\s*(['\"])([^'\"]+)\1", re.IGNORECASE)
GET_ID_RE = re.compile(r"\.getElementById\(\s*(['\"])([^'\"]+)\1\s*\)")
DOLLAR_ID_RE = re.compile(r"(?<![\w$])\$\(\s*(['\"])([^'\"]+)\1\s*\)")
QUERY_ID_RE = re.compile(r"\.querySelector(?:All)?\(\s*(['\"])#([A-Za-z][\w\-:.]*)\1\s*\)")
HANDLER_DIRECT_RE = re.compile(r"(?:\.onclick\s*=|\.addEventListener\s*\()")


def extract_html_constants(router: Path) -> dict[str, str]:
    tree = ast.parse(router.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for name in targets:
            if name in HTML_CONSTANTS:
                try:
                    value = ast.literal_eval(node.value)  # type: ignore[arg-type]
                except Exception as exc:
                    raise RuntimeError(f"Nao foi possivel ler {name}: {exc}") from exc
                if not isinstance(value, str):
                    raise RuntimeError(f"{name} nao e string")
                values[name] = value
    missing = [name for name in HTML_CONSTANTS if name not in values]
    if missing:
        raise RuntimeError("Constantes HTML nao encontradas: " + ", ".join(missing))
    return values


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() == "id" and value:
                self.ids.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def collect_ids(html: str) -> tuple[set[str], list[str]]:
    parser = _IdCollector()
    parser.feed(html)
    ids = parser.ids
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in ids:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return seen, duplicates


def collect_references(script: str) -> dict[str, set[str]]:
    refs = {
        "getElementById": {m.group(2) for m in GET_ID_RE.finditer(script)},
        "dollar_helper": {m.group(2) for m in DOLLAR_ID_RE.finditer(script)},
        "querySelector_id": {m.group(2) for m in QUERY_ID_RE.finditer(script)},
    }
    return refs


def validate_html(name: str, html: str, *, run_node: bool, temp_dir: Path) -> dict[str, object]:
    ids, duplicates = collect_ids(html)
    scripts = [m.group(1) for m in SCRIPT_RE.finditer(html)]
    missing_by_kind: dict[str, list[str]] = {}
    refs_total: dict[str, set[str]] = {"getElementById": set(), "dollar_helper": set(), "querySelector_id": set()}
    for script in scripts:
        refs = collect_references(script)
        for kind, values in refs.items():
            refs_total[kind].update(values)
    for kind, values in refs_total.items():
        missing = sorted(value for value in values if value not in ids)
        if missing:
            missing_by_kind[kind] = missing

    node_results: list[dict[str, object]] = []
    if run_node:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node nao encontrado para node --check")
        for idx, script in enumerate(scripts):
            script_path = temp_dir / f"{name}_{idx}.js"
            script_path.write_text(script, encoding="utf-8")
            proc = subprocess.run([node, "--check", str(script_path)], text=True, capture_output=True)
            node_results.append({"script": script_path.name, "returncode": proc.returncode, "stderr": proc.stderr.strip()})
            if proc.returncode != 0:
                raise RuntimeError(f"node --check falhou em {script_path.name}: {proc.stderr.strip()}")

    if duplicates:
        raise RuntimeError(f"{name}: IDs duplicados: {', '.join(duplicates)}")
    if missing_by_kind:
        raise RuntimeError(f"{name}: referencias JS sem ID HTML: {json.dumps(missing_by_kind, ensure_ascii=False, sort_keys=True)}")
    return {
        "html": name,
        "ids": len(ids),
        "scripts": len(scripts),
        "references": {kind: len(values) for kind, values in refs_total.items()},
        "node_checked": bool(run_node),
        "node_scripts": len(node_results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida HTML/JS embutidos do Equalizador/TR4.")
    parser.add_argument("--router", default="app/equalizador/router.py", help="Caminho do router.py")
    parser.add_argument("--skip-node", action="store_true", help="Nao executar node --check nos scripts extraidos")
    parser.add_argument("--json", action="store_true", help="Emitir resultado em JSON")
    args = parser.parse_args(argv)

    router = Path(args.router)
    if not router.exists():
        print(f"router nao encontrado: {router}", file=sys.stderr)
        return 2
    try:
        htmls = extract_html_constants(router)
        with tempfile.TemporaryDirectory(prefix="tr4_equalizador_js_") as tmp:
            temp_dir = Path(tmp)
            results = [validate_html(name, html, run_node=not args.skip_node, temp_dir=temp_dir) for name, html in htmls.items()]
    except Exception as exc:
        print(f"VALIDACAO_FALHOU: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("VALIDACAO_OK")
        for item in results:
            print(
                f"{item['html']}: ids={item['ids']} scripts={item['scripts']} "
                f"refs={item['references']} node_checked={item['node_checked']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
