# The stand-in add-on

`enlens_fake_addon` is a small add-on package that ENLENS's tests use, the way `tests/fake_claude_cli.py` stands in
for Claude Code. The folder is not installed: the `addon` fixture (`tests/addon_fixtures.py`) puts it on `sys.path`,
where Python finds its entry point (`enlens_fake_addon-0.1.dist-info/entry_points.txt`) under `enlens.extensions`,
exactly as it would find an installed package's.
