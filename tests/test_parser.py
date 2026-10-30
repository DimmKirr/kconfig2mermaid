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


def test_parse_no_annotations_included_by_default(tmp_path):
    (tmp_path / "plain.kconfig").write_text("menu \"Plain\"\nendmenu\n")
    modules, edges = parse(tmp_path)
    assert "PLAIN" in modules
    assert modules["PLAIN"]["name"] == "Plain"


def test_parse_ignore(tmp_path):
    (tmp_path / "internal.kconfig").write_text(
        "# kc2mm:ignore\nmenu \"Internal\"\nendmenu\n")
    (tmp_path / "visible.kconfig").write_text("menu \"Visible\"\nendmenu\n")
    modules, edges = parse(tmp_path)
    assert "INTERNAL" not in modules
    assert "VISIBLE" in modules


def test_reverse_trace_ignored_subfile(tmp_path):
    """Ignored files' cross-module deps create dashed edges from parent."""
    (tmp_path / "ui.kconfig").write_text(textwrap.dedent("""\
        menu "UI"
        config UI
            bool "Enable UI"
        config INPUT
            bool "Panel input"
        endmenu
    """))
    (tmp_path / "ble.kconfig").write_text(textwrap.dedent("""\
        menu "BLE"
        config BLE
            bool "Enable BLE"
        endmenu
    """))
    (tmp_path / "usb.kconfig").write_text(textwrap.dedent("""\
        menu "USB"
        config USB
            bool "Enable USB"
        endmenu
    """))
    (tmp_path / "settings.kconfig").write_text(textwrap.dedent("""\
        # kc2mm:ignore
        menu "Settings"
        config SETTINGS
            bool "Settings menu"
            depends on INPUT
        config SETTINGS_USB
            bool "USB setting"
            depends on SETTINGS && USB
        config SETTINGS_BLE
            bool "BLE setting"
            depends on SETTINGS && BLE
        endmenu
    """))
    modules, edges = parse(tmp_path, hal_module=None)
    assert "SETTINGS" not in modules
    dashed = [(e["from"], e["to"]) for e in edges if e["style"] == "dashed"]
    assert ("UI", "USB") in dashed
    assert ("UI", "BLE") in dashed
    # ignored file's menu title should appear as a component of the parent
    ui_comps = " · ".join(modules["UI"]["components"])
    assert "Settings" in ui_comps


def test_reverse_trace_negated_deps_skipped(tmp_path):
    """depends on !SYMBOL should not create an edge."""
    (tmp_path / "wifi.kconfig").write_text(textwrap.dedent("""\
        menu "WiFi"
        config WIFI
            bool "WiFi"
            depends on !BLE
        endmenu
    """))
    (tmp_path / "ble.kconfig").write_text(textwrap.dedent("""\
        menu "BLE"
        config BLE
            bool "BLE"
        endmenu
    """))
    modules, edges = parse(tmp_path, hal_module=None)
    wifi_to_ble = [e for e in edges if e["from"] == "WIFI" and e["to"] == "BLE"]
    assert wifi_to_ble == []


def test_parse_infer_edges(tmp_path):
    (tmp_path / "hal.kconfig").write_text(textwrap.dedent("""\
        menu "HAL"
        config HAL
            bool "Enable HAL"
        endmenu
    """))
    (tmp_path / "ble.kconfig").write_text(textwrap.dedent("""\
        menu "BLE"
        config BLE
            bool "Enable BLE"
            depends on HAL
            imply AUDIO
        endmenu
    """))
    (tmp_path / "audio.kconfig").write_text(textwrap.dedent("""\
        menu "Audio"
        config AUDIO
            bool "Enable Audio"
            select HAL_I2S
        endmenu
    """))
    modules, edges = parse(tmp_path, hal_module=None)
    solid = [(e["from"], e["to"]) for e in edges if e["style"] == "solid"]
    dashed = [(e["from"], e["to"]) for e in edges if e["style"] == "dashed"]
    assert ("BLE", "HAL") in solid
    assert ("AUDIO", "HAL") in solid
    assert ("BLE", "AUDIO") in dashed


def test_label_annotation_overrides_component_name(tmp_path):
    """# kc2mm:label on a config overrides its derived component name."""
    (tmp_path / "audio.kconfig").write_text(textwrap.dedent("""\
        menu "Audio"
        config AUDIO
            bool "Enable Audio"
        # kc2mm:label "Synth Render"
        config AUDIO_RENDER
            bool "Audio render pipeline"
        config AUDIO_FX
            bool "Effects chain"
        endmenu
    """))
    modules, edges = parse(tmp_path, hal_module=None)
    comps = " · ".join(modules["AUDIO"]["components"])
    assert "Synth Render" in comps
    assert "fx" in comps


def test_hide_annotation_excludes_component(tmp_path):
    """# kc2mm:hide on a config excludes it from component list."""
    (tmp_path / "audio.kconfig").write_text(textwrap.dedent("""\
        menu "Audio"
        config AUDIO
            bool "Enable Audio"
        config AUDIO_RENDER
            bool "Audio render pipeline"
        # kc2mm:hide
        config AUDIO_INTERNAL
            bool "Internal helper"
        config AUDIO_FX
            bool "Effects chain"
        endmenu
    """))
    modules, edges = parse(tmp_path, hal_module=None)
    comps = " · ".join(modules["AUDIO"]["components"])
    assert "render" in comps
    assert "fx" in comps
    assert "internal" not in comps.lower()


def test_ignored_file_contributes_component_to_parent(tmp_path):
    """Ignored sub-files contribute their menu title as a parent component."""
    (tmp_path / "audio.kconfig").write_text(textwrap.dedent("""\
        menu "Audio"
        config AUDIO
            bool "Enable Audio"
        config AUDIO_RENDER
            bool "Audio render pipeline"
        endmenu
    """))
    (tmp_path / "effects.kconfig").write_text(textwrap.dedent("""\
        # kc2mm:ignore
        menu "Effects"
        config FX_REVERB
            bool "Reverb"
            depends on AUDIO_RENDER
        endmenu
    """))
    (tmp_path / "engines.kconfig").write_text(textwrap.dedent("""\
        # kc2mm:ignore
        menu "Engines"
        config ENGINE_FM
            bool "FM engine"
            depends on AUDIO
        endmenu
    """))
    modules, edges = parse(tmp_path, hal_module=None)
    assert "FX_REVERB" not in modules
    assert "ENGINE_FM" not in modules
    comps = " · ".join(modules["AUDIO"]["components"])
    assert "render" in comps
    assert "Effects" in comps
    assert "Engines" in comps
