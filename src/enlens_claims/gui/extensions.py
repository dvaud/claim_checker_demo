"""This installation's own add-on: the local layer's Python file (0.13.5). ENLENS ships it empty and its releases
never edit it.

A fork of ENLENS fills it in; ENLENS reads only the names defined here and keeps its own defaults for the rest. A
separate package does the same in a module of its own, named under the entry point `enlens.extensions`. What each
name does, with an example, is in docs/EXTENDING.md; for instance:

    BRAND = {"name": "Margin", "tagline": "a writing companion"}
"""
