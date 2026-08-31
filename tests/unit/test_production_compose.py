from pathlib import Path


def test_production_web_slots_have_bast_renderer_memory_headroom() -> None:
    text = Path("compose.production.yaml").read_text(encoding="utf-8")

    assert "web-blue:" in text
    assert "web-green:" in text
    assert text.count("memory: 1.5G") == 2
