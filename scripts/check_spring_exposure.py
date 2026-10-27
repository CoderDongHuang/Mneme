"""Time-limited guard for the documented Spring view-rendering exceptions."""
from datetime import date
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT, today=None):
    if (today or date.today()) > date(2026, 11, 10):
        raise RuntimeError("Spring applicability exception expired; review upstream patches")
    source = root / "java-gateway"
    forbidden = re.compile(r"FragmentsRendering|ModelAndView|XsltView|ViewResolver|\.fragment\s*\(")
    for path in (source / "src/main").rglob("*.java"):
        if forbidden.search(path.read_text(encoding="utf-8")):
            raise RuntimeError(f"View rendering invalidates Spring exception: {path}")
    pom = (source / "pom.xml").read_text(encoding="utf-8")
    if re.search(r"thymeleaf|freemarker|mustache|spring-boot-starter-webflux|spring-webflux", pom):
        raise RuntimeError("Template/WebFlux dependency requires new security review")
    for name in ("templates", "WEB-INF"):
        if any((source / "src/main").rglob(name)):
            raise RuntimeError("View resources require new security review")


if __name__ == "__main__":
    check()
    print("Spring view-rendering applicability guard passed (expires 2026-11-10)")
