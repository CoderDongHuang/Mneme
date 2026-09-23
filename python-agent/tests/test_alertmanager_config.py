from pathlib import Path


def test_alertmanager_has_configured_receiver_and_inhibition_rule():
    config = Path(__file__).resolve().parents[2] / "observability" / "alertmanager.yml"
    text = config.read_text(encoding="utf-8")
    assert "webhook_configs:" in text
    assert "${ALERTMANAGER_WEBHOOK_URL}" in text
    assert "source_matchers: [severity=\"critical\"]" in text
    assert "send_resolved: true" in text
