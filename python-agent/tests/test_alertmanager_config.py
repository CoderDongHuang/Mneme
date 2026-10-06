from pathlib import Path

import importlib.util

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("render_alertmanager_config", ROOT / "scripts/render_alertmanager_config.py")
assert SPEC and SPEC.loader
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def test_alertmanager_has_configured_receiver_and_inhibition_rule():
    config = ROOT / "observability" / "alertmanager.yml"
    text = config.read_text(encoding="utf-8")
    assert "webhook_configs:" in text
    assert "${ALERTMANAGER_WEBHOOK_URL}" in text
    assert "source_matchers: [severity=\"critical\"]" in text
    assert "send_resolved: true" in text


def test_rendered_config_has_all_receiver_urls_and_valid_yaml(tmp_path):
    output = tmp_path / "data/alertmanager.yml"
    url = "https://example.org/hook?token=a%3Ab&channel=critical"
    RENDERER.render(ROOT / "observability/alertmanager.yml", output, url)
    config = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert [item["url"] for receiver in config["receivers"] for item in receiver["webhook_configs"]] == [url] * 3
    assert "${ALERTMANAGER_WEBHOOK_URL}" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("url", ["", "ftp://example.org", "http://", "https://example.org:bad", "https://example.org/#fragment", "http://user:pass@example.org", "https://example.org/\nunsafe"])
def test_renderer_rejects_bad_url_without_writing(tmp_path, url):
    output = tmp_path / "alertmanager.yml"
    with pytest.raises(ValueError, match="valid HTTP\\(S\\) URL") as exc:
        RENDERER.render(ROOT / "observability/alertmanager.yml", output, url)
    if url:
        assert url not in str(exc.value)
    assert not output.exists()


def test_renderer_preserves_existing_config_on_invalid_template(tmp_path):
    template = tmp_path / "template.yml"
    template.write_text("receivers: [{name: default, webhook_configs: [{url: '${ALERTMANAGER_WEBHOOK_URL}'}]}]", encoding="utf-8")
    output = tmp_path / "alertmanager.yml"
    output.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="three webhook placeholders"):
        RENDERER.render(template, output, "https://example.org/hook")
    assert output.read_text(encoding="utf-8") == "existing"
