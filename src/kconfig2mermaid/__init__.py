"""Generate Mermaid module diagrams from Kconfig @module annotations."""

from kconfig2mermaid.parser import parse
from kconfig2mermaid.renderer import render
from kconfig2mermaid.inject import wrap_block, replace_in_doc

__all__ = ["parse", "render", "wrap_block", "replace_in_doc"]
