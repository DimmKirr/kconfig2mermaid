"""Tests for kconfig2mermaid parser and renderer."""
import textwrap
from pathlib import Path

import pytest

from kconfig2mermaid.parser import parse
from kconfig2mermaid.renderer import render
from kconfig2mermaid.inject import wrap_block, replace_in_doc


@pytest.fixture
def kconf_dir(tmp_path):
    """Create a minimal kconfig directory for testing."""
    (tmp_path / "hal.kconfig").write_text(textwrap.dedent("""\
        # @module HAL "Hardware Abstraction"
        menu "HAL"
        config HAL_SPI
            bool "SPI driver"
        endmenu
    """))
    (tmp_path / "audio.kconfig").write_text(textwrap.dedent("""\
        # @module AUDIO
        # @module AUDIO -> HAL
        menu "Audio"
        choice
            prompt "Audio core"
        config AUDIO_CORE_A
            bool "Core A"
        config AUDIO_CORE_B
            bool "Core B"
        endchoice
        endmenu
    """))
    return tmp_path


def test_parse_finds_modules(kconf_dir):
    modules, edges = parse(kconf_dir)
    assert "HAL" in modules
    assert "AUDIO" in modules
    assert modules["HAL"]["name"] == "Hardware Abstraction"
    assert modules["AUDIO"]["name"] == "Audio"


def test_parse_auto_hal_edges(kconf_dir):
    modules, edges = parse(kconf_dir)
    hal_targets = [e for e in edges if e["to"] == "HAL"]
    sources = {e["from"] for e in hal_targets}
    assert "AUDIO" in sources


def test_parse_explicit_edge(kconf_dir):
    modules, edges = parse(kconf_dir)
    explicit = [e for e in edges if e["from"] == "AUDIO" and e["to"] == "HAL"
                and e["style"] == "solid"]
    assert len(explicit) >= 1


def test_parse_auto_components(kconf_dir):
    modules, _ = parse(kconf_dir)
    assert modules["AUDIO"]["components"]


def test_parse_no_hal_module(kconf_dir):
    modules, edges = parse(kconf_dir, hal_module=None)
    auto_hal = [e for e in edges if e["to"] == "HAL" and e["style"] == "solid"
                and e["from"] == "AUDIO" and e["label"] is None]
    explicit = [e for e in edges if e["from"] == "AUDIO" and e["to"] == "HAL"]
    assert len(explicit) == 1


def test_render_produces_mermaid(kconf_dir):
    modules, edges = parse(kconf_dir)
    mermaid = render(modules, edges)
    assert "flowchart TB" in mermaid
    assert "HAL" in mermaid
    assert "AUDIO" in mermaid
    assert "-->" in mermaid


def test_render_direction(kconf_dir):
    modules, edges = parse(kconf_dir)
    mermaid = render(modules, edges, direction="LR")
    assert "flowchart LR" in mermaid


def test_wrap_block():
    block = wrap_block("flowchart TB\n    A --> B")
    assert "```mermaid" in block
    assert "<!-- module-diagram:start -->" in block
    assert "<!-- module-diagram:end -->" in block


def test_replace_in_doc():
    doc = "before\n<!-- module-diagram:start -->\nold\n<!-- module-diagram:end -->\nafter"
    new_block = wrap_block("flowchart TB\n    X --> Y")
    result = replace_in_doc(doc, new_block)
    assert "X --> Y" in result
    assert "old" not in result
    assert "before" in result
    assert "after" in result


def test_replace_in_doc_missing_markers():
    with pytest.raises(ValueError, match="Markers not found"):
        replace_in_doc("no markers here", "new block")


def test_parse_dashed_edge(tmp_path):
    (tmp_path / "wifi.kconfig").write_text(textwrap.dedent("""\
        # @module WIFI
        # @module WIFI --> HAL "optional"
        menu "WiFi"
        endmenu
    """))
    (tmp_path / "hal.kconfig").write_text(textwrap.dedent("""\
        # @module HAL
        menu "HAL"
        endmenu
    """))
    modules, edges = parse(tmp_path)
    dashed = [e for e in edges if e["style"] == "dashed"]
    assert len(dashed) == 1
    assert dashed[0]["label"] == "optional"


def test_parse_explicit_components(tmp_path):
    (tmp_path / "debug.kconfig").write_text(textwrap.dedent("""\
        # @module DEBUG
        # @module DEBUG : log · sysex · dap
        menu "Debug"
        endmenu
    """))
    modules, _ = parse(tmp_path, hal_module=None)
    assert "DEBUG" in modules
    assert "log · sysex · dap" in modules["DEBUG"]["components"]


def test_parse_empty_dir(tmp_path):
    modules, edges = parse(tmp_path)
    assert modules == {}
    assert edges == []


def test_parse_no_annotations(tmp_path):
    (tmp_path / "plain.kconfig").write_text("menu \"Plain\"\nendmenu\n")
    modules, edges = parse(tmp_path)
    assert modules == {}
