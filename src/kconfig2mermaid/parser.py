"""Parse Kconfig files into module diagrams.

Every .kconfig file is included as a module by default.
Add '# kc2mm:ignore' to exclude a file from the diagram.

Optional overrides (in kconfig comment lines):
    # @module ID                          override module ID (default: from filename)
    # @module ID "Override Name"          override display name (default: from menu title)
    # @module [ID] : comp · list          override auto-derived component list
    # @module [ID] -> TARGET              explicit solid arrow (hard dependency)
    # @module [ID] --> TARGET "label"     explicit dashed arrow with label

Auto-derived:
    - Module ID from filename (ble.kconfig -> BLE)
    - Display name from 'menu "Title"' in the file
    - Components from choice prompts (short labels) and standalone config symbols
    - Cross-module edges from depends on/select (solid) and imply (dashed)
    - '-> HAL' edge for every non-HAL module (when a HAL module exists and
      no dependency on HAL was already inferred)
"""
import re
from pathlib import Path

ACRONYMS = {"MIDI", "HID", "USB", "BLE", "HAL", "SPI", "I2S", "OTA",
            "DMA", "WPA", "DAP", "CDP", "FT", "ADC", "CDC", "GM",
            "UART", "LCD"}
KNOWN_LABELS = {"LWIP": "lwIP"}
KNOWN_SHORT = {"multicore": "mc"}
UPSTREAM_NAMES = {"FELUCCA", "SLOOP", "MELODEE", "FMLAB", "OPTIMIST", "CORE"}
SKIP_SYMBOLS = {"GEN_FELUCCA_UI", "ENGINES"}
SKIP_WORDS = {"stub", "test"}
MAX_COMPONENTS_PER_LINE = 6

RE_IGNORE = re.compile(r'^#\s*kc2mm:ignore\b')
RE_LABEL = re.compile(r'^#\s*kc2mm:label\s+"([^"]+)"')
RE_HIDE = re.compile(r'^#\s*kc2mm:hide\b')
RE_MOD_BARE = re.compile(r'^#\s*@module\s*$')
RE_MOD_ID = re.compile(r'^#\s*@module\s+(\w+)\s*$')
RE_MOD_NAMED = re.compile(r'^#\s*@module\s+(\w+)\s+"([^"]+)"\s*$')
RE_COMP = re.compile(r'^#\s*@module\s+(?:(\w+)\s+)?:\s*(.+)$')
RE_EDGE_SOLID = re.compile(r'^#\s*@module\s+(?:(\w+)\s+)?->\s+(\w+)\s*$')
RE_EDGE_DASHED = re.compile(r'^#\s*@module\s+(?:(\w+)\s+)?-->\s+(\w+)\s*(?:"([^"]+)")?\s*$')
RE_MENU = re.compile(r'^menu\s+"([^"]+)"')
RE_CONFIG = re.compile(r'^config\s+(\w+)')
RE_BOOL_PROMPT = re.compile(r'^\s+bool\s+"([^"]+)"')
RE_CHOICE = re.compile(r'^choice\b')
RE_CHOICE_PROMPT = re.compile(r'^\s+prompt\s+"([^"]+)"')
RE_ENDCHOICE = re.compile(r'^endchoice\b')
RE_DEPENDS = re.compile(r'^\s+depends\s+on\s+(.+)$')
RE_SELECT = re.compile(r'^\s+select\s+(\w+)')
RE_IMPLY = re.compile(r'^\s+imply\s+(\w+)')
RE_SYMBOL_REF = re.compile(r'(?<!!)\b([A-Z][A-Z0-9_]*)\b')


def _id_from_filename(path):
    """ble.kconfig -> BLE, sys_menu.kconfig -> SYS_MENU."""
    return path.stem.upper()


def _strip_upstream(name):
    parts = name.split("_")
    filtered = [p for p in parts if p not in UPSTREAM_NAMES]
    return "_".join(filtered)


def _symbol_to_label(symbol, prefix, long_names=False):
    name = symbol
    if prefix and name.startswith(prefix):
        name = name[len(prefix):]

    if name in KNOWN_LABELS:
        return KNOWN_LABELS[name]

    if not long_names:
        stripped = _strip_upstream(name)
        if not stripped:
            return None
        short = stripped.lower()
        if short in KNOWN_SHORT:
            return KNOWN_SHORT[short]
        return short

    parts = name.split("_")
    result = []
    for p in parts:
        if p.upper() in ACRONYMS:
            result.append(p.upper())
        else:
            result.append(p.capitalize())
    return " ".join(result)


def _choice_label(prompt, first_config, module_prefix, long_names=False):
    if first_config:
        name = first_config
        if module_prefix and name.startswith(module_prefix):
            name = name[len(module_prefix):]
        stripped = _strip_upstream(name)
        if stripped:
            if long_names:
                return prompt
            short = stripped.lower()
            return KNOWN_SHORT.get(short, short)

    if long_names:
        return prompt
    word = prompt.split("(")[0].strip().split()[0].lower()
    return KNOWN_SHORT.get(word, word)


def _auto_derive_components(file_lines, module_id, long_names=False):
    components = []
    prefix = module_id + "_"
    i = 0

    while i < len(file_lines):
        line = file_lines[i]

        if RE_CHOICE.match(line):
            custom_label = None
            hidden = False
            if i > 0:
                lm = RE_LABEL.match(file_lines[i - 1])
                if lm:
                    custom_label = lm.group(1)
                if RE_HIDE.match(file_lines[i - 1]):
                    hidden = True

            prompt = None
            first_config = None
            j = i + 1
            while j < len(file_lines) and not RE_ENDCHOICE.match(file_lines[j]):
                pm = RE_CHOICE_PROMPT.match(file_lines[j])
                if pm:
                    prompt = pm.group(1)
                if first_config is None:
                    cm = RE_CONFIG.match(file_lines[j])
                    if cm:
                        first_config = cm.group(1)
                j += 1

            if not hidden and prompt:
                label = custom_label or _choice_label(
                    prompt, first_config, prefix, long_names)
                if label and not any(w in label.lower() for w in SKIP_WORDS):
                    if label not in components:
                        components.append(label)
            i = j + 1
            continue

        cm = RE_CONFIG.match(line)
        if cm:
            sym = cm.group(1)

            custom_label = None
            hidden = False
            if i > 0:
                lm = RE_LABEL.match(file_lines[i - 1])
                if lm:
                    custom_label = lm.group(1)
                if RE_HIDE.match(file_lines[i - 1]):
                    hidden = True

            if sym == module_id or sym in SKIP_SYMBOLS:
                if custom_label and not hidden:
                    components.append(custom_label)
                i += 1
                continue

            j = i + 1
            is_visible = False
            while j < len(file_lines):
                stripped = file_lines[j].strip()
                if not stripped or RE_CONFIG.match(file_lines[j]) or \
                   RE_MENU.match(file_lines[j]) or RE_CHOICE.match(file_lines[j]):
                    break
                if RE_BOOL_PROMPT.match(file_lines[j]):
                    is_visible = True
                j += 1

            if hidden:
                pass
            elif custom_label:
                components.append(custom_label)
            elif is_visible:
                label = _symbol_to_label(sym, prefix, long_names)
                if label and not any(w in label.lower() for w in SKIP_WORDS):
                    components.append(label)
        i += 1

    return components


def _resolve_module(symbol, modules, source_module):
    """Find which module a symbol belongs to, if not the source module."""
    if symbol in modules and symbol != source_module:
        return symbol
    for mid in modules:
        if mid != source_module and symbol.startswith(mid + "_"):
            return mid
    return None


def _infer_edges(modules, file_refs):
    """Infer cross-module edges from depends on/select/imply references."""
    edges = []
    seen = set()
    for src_module, refs in file_refs.items():
        for dep_type, symbol in refs:
            target = _resolve_module(symbol, modules, src_module)
            if target:
                style = "dashed" if dep_type == "imply" else "solid"
                key = (src_module, target, style)
                if key not in seen:
                    seen.add(key)
                    edges.append({"from": src_module, "to": target,
                                  "style": style, "label": None})
    return edges


def _collect_kconfig_refs(file_lines):
    """Collect all depends on/select/imply symbol references from a file."""
    refs = []
    for line in file_lines:
        m = RE_DEPENDS.match(line)
        if m:
            for sym in RE_SYMBOL_REF.findall(m.group(1)):
                refs.append(("depends", sym))
            continue
        m = RE_SELECT.match(line)
        if m:
            refs.append(("select", m.group(1)))
            continue
        m = RE_IMPLY.match(line)
        if m:
            refs.append(("imply", m.group(1)))
    return refs


def _collect_refs_by_config(file_lines):
    """Collect refs grouped by the config symbol they belong to.

    Returns list of (config_symbol, [(dep_type, referenced_symbol), ...]).
    Menu-level depends-on lines (before any config) use None as the symbol.
    """
    groups = []
    current_sym = None
    current_refs = []

    for line in file_lines:
        cm = RE_CONFIG.match(line)
        if cm:
            if current_refs:
                groups.append((current_sym, current_refs))
            current_sym = cm.group(1)
            current_refs = []
            continue

        if RE_CHOICE.match(line):
            if current_refs:
                groups.append((current_sym, current_refs))
            current_sym = None
            current_refs = []
            continue

        m = RE_DEPENDS.match(line)
        if m:
            for sym in RE_SYMBOL_REF.findall(m.group(1)):
                current_refs.append(("depends", sym))
            continue
        m = RE_SELECT.match(line)
        if m:
            current_refs.append(("select", m.group(1)))
            continue
        m = RE_IMPLY.match(line)
        if m:
            current_refs.append(("imply", m.group(1)))

    if current_refs:
        groups.append((current_sym, current_refs))
    return groups


def _reverse_trace_ignored(ignored_files, modules, symbol_to_module, edges,
                           parent_components):
    """Scan ignored files for cross-module deps and add dashed edges.

    For each ignored file, determine a parent module (the module owning the
    first cross-module symbol referenced in a depends-on line). Other
    cross-module references become dashed edges from parent to target.
    The ignored file's menu title is contributed as a component of the parent.
    """
    existing = {(e["from"], e["to"]) for e in edges}

    for _kf, file_lines in ignored_files:
        refs = _collect_kconfig_refs(file_lines)

        menu_title = None
        for line in file_lines:
            mm = RE_MENU.match(line)
            if mm:
                menu_title = mm.group(1)
                break

        if not refs:
            continue

        parent = None
        targets = []
        for dep_type, symbol in refs:
            target = symbol_to_module.get(symbol)
            if not target or target not in modules:
                target = _resolve_module(symbol, modules, None)
            if target and target in modules:
                if parent is None:
                    parent = target
                elif target != parent:
                    targets.append(target)

        if not parent:
            continue

        if menu_title:
            parent_components.setdefault(parent, []).append(menu_title)

        seen = set()
        for target in targets:
            if target not in seen and (parent, target) not in existing:
                seen.add(target)
                existing.add((parent, target))
                edges.append({"from": parent, "to": target,
                              "style": "dashed", "label": None})


def _group_components(components):
    result = []
    for i in range(0, len(components), MAX_COMPONENTS_PER_LINE):
        chunk = components[i:i + MAX_COMPONENTS_PER_LINE]
        result.append(" · ".join(chunk))
    return result


def parse(kconf_dir, *, hal_module="HAL", skip_symbols=None, long_names=False):
    """Parse a kconfig directory for @module annotations.

    Args:
        kconf_dir: Path to directory containing *.kconfig files.
        hal_module: Module ID to auto-add edges to (None to disable).
        skip_symbols: Extra symbols to exclude from component derivation.
        long_names: Use full choice prompt text instead of short symbol-derived labels.

    Returns:
        (modules, edges) where modules is {id: {name, components, order}}
        and edges is [{from, to, style, label}].
    """
    if skip_symbols:
        SKIP_SYMBOLS.update(skip_symbols)

    kconf_dir = Path(kconf_dir)
    modules = {}
    edges = []
    file_refs = {}
    symbol_to_module = {}
    ignored_files = []
    order = 0

    for kf in sorted(kconf_dir.glob("*.kconfig")):
        file_lines = kf.read_text().splitlines()
        file_default_id = _id_from_filename(kf)

        if any(RE_IGNORE.match(line) for line in file_lines):
            ignored_files.append((kf, file_lines))
            continue

        file_module_ids = []
        file_has_comp_override = set()

        for line in file_lines:
            if RE_MOD_BARE.match(line):
                mid = file_default_id
                if mid not in modules:
                    file_module_ids.append(mid)
                    modules[mid] = {"name": None, "components": [],
                                    "order": order}
                    order += 1
                continue

            m = RE_MOD_NAMED.match(line)
            if m:
                mid, name = m.group(1), m.group(2)
                if mid not in modules:
                    file_module_ids.append(mid)
                    modules[mid] = {"name": name, "components": [],
                                    "order": order}
                    order += 1
                else:
                    modules[mid]["name"] = name
                continue

            m = RE_MOD_ID.match(line)
            if m:
                mid = m.group(1)
                if mid not in modules:
                    file_module_ids.append(mid)
                    modules[mid] = {"name": None, "components": [],
                                    "order": order}
                    order += 1
                continue

            m = RE_COMP.match(line)
            if m:
                mid = m.group(1) or (file_module_ids[0] if file_module_ids else file_default_id)
                comps = m.group(2).strip()
                file_has_comp_override.add(mid)
                if mid not in modules:
                    file_module_ids.append(mid)
                    modules[mid] = {"name": None, "components": [],
                                    "order": order}
                    order += 1
                modules[mid]["components"].append(comps)
                continue

            m = RE_EDGE_SOLID.match(line)
            if m:
                src = m.group(1) or (file_module_ids[0] if file_module_ids else file_default_id)
                edges.append({"from": src, "to": m.group(2),
                              "style": "solid", "label": None})
                continue

            m = RE_EDGE_DASHED.match(line)
            if m:
                src = m.group(1) or (file_module_ids[0] if file_module_ids else file_default_id)
                edges.append({"from": src, "to": m.group(2),
                              "style": "dashed", "label": m.group(3)})
                continue

        if not file_module_ids:
            mid = file_default_id
            file_module_ids.append(mid)
            if mid not in modules:
                modules[mid] = {"name": None, "components": [],
                                "order": order}
                order += 1

        menu_title = None
        for line in file_lines:
            mm = RE_MENU.match(line)
            if mm:
                menu_title = mm.group(1)
                break

        for mid in file_module_ids:
            mod = modules[mid]
            if mod["name"] is None:
                if mid == file_default_id and menu_title:
                    mod["name"] = menu_title
                else:
                    mod["name"] = mid

        for mid in file_module_ids:
            if mid not in file_has_comp_override:
                auto = _auto_derive_components(file_lines, mid, long_names)
                if auto:
                    modules[mid]["components"] = _group_components(auto)

        for line in file_lines:
            cm = RE_CONFIG.match(line)
            if cm:
                sym = cm.group(1)
                if file_module_ids:
                    for mid in file_module_ids:
                        if sym == mid or sym.startswith(mid + "_"):
                            symbol_to_module[sym] = mid
                            break
                    else:
                        symbol_to_module[sym] = file_module_ids[0]

        if len(file_module_ids) > 1:
            ref_groups = _collect_refs_by_config(file_lines)
            for config_sym, refs in ref_groups:
                owner = None
                if config_sym:
                    owner = symbol_to_module.get(config_sym)
                if not owner:
                    owner = file_module_ids[0]
                file_refs.setdefault(owner, []).extend(refs)
        else:
            refs = _collect_kconfig_refs(file_lines)
            if refs:
                for mid in file_module_ids:
                    file_refs.setdefault(mid, []).extend(refs)

    parent_components = {}
    _reverse_trace_ignored(ignored_files, modules, symbol_to_module, edges,
                           parent_components)
    for mid, comps in parent_components.items():
        if mid in modules:
            existing_lines = modules[mid].get("components") or []
            flat = []
            for line in existing_lines:
                flat.extend(c.strip() for c in line.split("·") if c.strip())
            flat.extend(comps)
            modules[mid]["components"] = _group_components(flat)

    inferred = _infer_edges(modules, file_refs)
    existing = {(e["from"], e["to"], e["style"]) for e in edges}
    for e in inferred:
        if (e["from"], e["to"], e["style"]) not in existing:
            edges.append(e)

    if hal_module and hal_module in modules:
        hal_edges = {e["from"] for e in edges if e["to"] == hal_module}
        for mid in modules:
            if mid != hal_module and mid not in hal_edges:
                edges.append({"from": mid, "to": hal_module,
                              "style": "solid", "label": None})

    return modules, edges
