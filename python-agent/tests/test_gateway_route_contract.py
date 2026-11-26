"""Keep browser Gateway routes aligned with Java controller mappings.

The client is the public consumer of the Gateway.  Parsing both sides in the
test avoids maintaining a second hand-written route list that can drift from
the controllers themselves.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_ROOT = ROOT / "java-gateway/src/main/java/com/mneme/controller"
CLIENT = ROOT / "frontend/src/api/client.js"


def _annotation_path(arguments: str | None) -> str:
    if not arguments:
        return ""
    match = re.search(r'"([^"\n]*)"', arguments)
    return match.group(1) if match else ""


def _java_routes() -> set[str]:
    routes: set[str] = set()
    for source in CONTROLLER_ROOT.glob("*.java"):
        text = source.read_text(encoding="utf-8")
        class_mapping = re.search(
            r"@RequestMapping(?:\(([^)]*)\))?", text, re.DOTALL
        )
        prefix = _annotation_path(class_mapping.group(1) if class_mapping else None)
        for mapping in re.finditer(
            r"@(Get|Post|Put|Delete|Patch)Mapping(?:\(([^)]*)\))?",
            text,
            re.DOTALL,
        ):
            suffix = _annotation_path(mapping.group(2))
            routes.add(f"{prefix.rstrip('/')}/{suffix.lstrip('/')}")
    return {route.replace("//", "/") for route in routes}


def _replace_template_expressions(value: str) -> str:
    """Replace JavaScript template expressions without parsing JavaScript."""
    result: list[str] = []
    index = 0
    while index < len(value):
        start = value.find("${", index)
        if start < 0:
            result.append(value[index:])
            break
        result.append(value[index:start])
        depth = 1
        end = start + 2
        while end < len(value) and depth:
            if value[end] == "{":
                depth += 1
            elif value[end] == "}":
                depth -= 1
            end += 1
        result.append("{value}")
        index = end
    return "".join(result)


def _client_routes() -> set[str]:
    text = CLIENT.read_text(encoding="utf-8")
    routes: set[str] = set()

    # API helpers use either a quoted path or a template path.
    for match in re.finditer(r"\bapi\(\s*(['\"`])([\s\S]*?)\1", text):
        raw_path = re.sub(r"(\/preview)\$\{.*$", r"\1", match.group(2))
        path = _replace_template_expressions(raw_path).split("?")[0]
        if path.startswith("/"):
            routes.add("/api/v1" + path)

    # Streaming and binary endpoints call fetch/EventSource directly.
    for match in re.finditer(r"(?:fetch|EventSourceClass)\(\s*`\$\{API_BASE\}([\s\S]*?)`", text):
        raw_path = match.group(1)
        if raw_path.startswith("${"):
            continue
        path = _replace_template_expressions(raw_path).split("?")[0]
        routes.add("/api/v1" + path)
    return {route.replace("//", "/") for route in routes}


def _shape(route: str) -> str:
    return re.sub(r"\{[^/]+\}", "{value}", route.rstrip("/"))


def test_browser_gateway_routes_exist_in_java_controllers():
    java_routes = {_shape(route) for route in _java_routes()}
    client_routes = _client_routes()
    missing = sorted(route for route in client_routes if _shape(route) not in java_routes)
    assert not missing, "Frontend calls routes without a Java controller mapping: " + ", ".join(missing)

