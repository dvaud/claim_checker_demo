"""A stand-in add-on for ENLENS's tests, as tests/fake_claude_cli.py stands in for Claude Code.

It is a separate package: tests put this folder on sys.path, where the entry point in
enlens_fake_addon-0.1.dist-info/entry_points.txt names it under `enlens.extensions`. Each ENLENS version that adds an
extension point adds what this add-on does with it, so every extension point is tried from outside ENLENS.
"""
from pathlib import Path

BRAND = {"name": "Fieldnotes", "tagline": "a stand-in app on ENLENS", "welcome_title": "Welcome to Fieldnotes",
         "not_a_brand_key": "ignored"}
STATIC = Path(__file__).with_name("static")
