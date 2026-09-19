import re
from dataclasses import dataclass
from typing import Any


_SENSITIVE_PATTERNS = {
    "email": re.compile(r"(?<![\w.-])[\w.+-]+@(?!example\.(?:test|com)\b)[\w.-]+\.[A-Za-z]{2,}"),
    "mainland_phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "mainland_id": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "api_key": re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
}
_SENSITIVE_KEYS = {"api_key", "apikey", "password", "secret", "token"}


def sensitive_findings(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _SENSITIVE_KEYS and item not in (None, "", [], {}):
                findings.append(f"{path}.{key}: sensitive_field")
            findings.extend(sensitive_findings(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(sensitive_findings(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        for label, pattern in _SENSITIVE_PATTERNS.items():
            if pattern.search(value):
                findings.append(f"{path}: {label}")
    return findings


def require_sanitized(value: Any) -> None:
    findings = sensitive_findings(value)
    if findings:
        raise ValueError("评测数据未通过脱敏检查: " + ", ".join(findings[:10]))


@dataclass
class CostBudget:
    max_usd: float
    input_cost_per_million: float
    output_cost_per_million: float
    reserved_usd: float = 0.0

    def reserve(self, input_tokens: int, output_tokens: int, label: str) -> float:
        cost = (
            max(0, input_tokens) / 1_000_000 * max(0.0, self.input_cost_per_million)
            + max(0, output_tokens) / 1_000_000 * max(0.0, self.output_cost_per_million)
        )
        if self.max_usd <= 0:
            raise ValueError("真实模型评测必须配置正数预算上限")
        if self.reserved_usd + cost > self.max_usd:
            raise RuntimeError(
                f"{label} 将超过评测预算: "
                f"{self.reserved_usd + cost:.6f} > {self.max_usd:.6f} USD"
            )
        self.reserved_usd += cost
        return cost
