"""Render parsed module data into Mermaid flowchart syntax."""


def render(modules, edges, *, direction="TB", curve="step"):
    """Render modules and edges into a mermaid flowchart string.

    Args:
        modules: Dict from parse().
        edges: List from parse().
        direction: Mermaid flowchart direction (TB, LR, etc.).
        curve: Mermaid curve style.

    Returns:
        Mermaid flowchart as a string.
    """
    lines = [
        f'%%{{init: {{"flowchart": {{"curve": "{curve}"}}}} }}%%',
        f'flowchart {direction}',
    ]

    sorted_mods = sorted(modules.items(), key=lambda kv: kv[1]["order"])

    for mid, mod in sorted_mods:
        label_parts = [f'<b>{mod["name"]}</b>']
        if mod["components"]:
            comp_html = "<br/>".join(mod["components"])
            label_parts.append(f'<small>{comp_html}</small>')
        label = "<br/>".join(label_parts)
        lines.append(f'    {mid}["{label}"]')

    lines.append("")

    for edge in edges:
        src, dst = edge["from"], edge["to"]
        if edge["style"] == "solid":
            lines.append(f"    {src} --> {dst}")
        elif edge["label"]:
            lines.append(f"    {src} -.->|{edge['label']}| {dst}")
        else:
            lines.append(f"    {src} -.-> {dst}")

    return "\n".join(lines)
