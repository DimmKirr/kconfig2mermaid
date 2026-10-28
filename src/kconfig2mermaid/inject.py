"""Inject/update mermaid diagrams in markdown files."""

DEFAULT_START_MARKER = "<!-- module-diagram:start -->"
DEFAULT_END_MARKER = "<!-- module-diagram:end -->"


def wrap_block(mermaid, start_marker=None, end_marker=None):
    """Wrap mermaid in a marker-delimited fenced code block."""
    start = start_marker or DEFAULT_START_MARKER
    end = end_marker or DEFAULT_END_MARKER
    return f"{start}\n```mermaid\n{mermaid}\n```\n{end}"


def replace_in_doc(doc_text, new_block, start_marker=None, end_marker=None):
    """Replace content between markers in a document string."""
    start = start_marker or DEFAULT_START_MARKER
    end = end_marker or DEFAULT_END_MARKER
    start_idx = doc_text.find(start)
    end_idx = doc_text.find(end)
    if start_idx == -1 or end_idx == -1:
        raise ValueError(f"Markers not found: {start} / {end}")
    end_idx += len(end)
    return doc_text[:start_idx] + new_block + doc_text[end_idx:]
