#!/bin/sh
# ENLENS one-line install for macOS and Linux (0.10). Paste this in Terminal:
#
#   curl -fsSL https://github.com/dvaud/claim_checker_demo/releases/latest/download/install.sh | sh
#
# It needs no git, no Python and no venv of your own:
#   1. gets uv (a small tool from Astral that installs Python programs), unless it is already here;
#   2. downloads the ENLENS package of this release and checks it against the release's checksums;
#   3. installs ENLENS with uv, which brings its own Python (3.12) and keeps it apart from any other Python;
#   4. makes the ENLENS icon (macOS: Applications and Desktop; Linux: the applications menu) and opens ENLENS.
# Running the same line again installs the newest release over this one: your projects (in ~/enlens) stay as they are.
#
# Options, as environment variables before `sh`:
#   ENLENS_LOCAL_ONLY=1   nothing may leave this computer (no cloud AI; built into the icon)
#   ENLENS_HOME=<folder>  keep projects and settings in another folder (built into the icon)
#   ENLENS_VERSION=0.10.0 install that release instead of the one this script came with
#   ENLENS_WHEEL=<file>   install this package file instead of downloading one (for testing a build)
#   ENLENS_NO_OPEN=1      do not open ENLENS at the end
set -eu

REPO="${ENLENS_REPO:-dvaud/claim_checker_demo}"
VERSION="${ENLENS_VERSION:-@ENLENS_VERSION@}"
EXTRAS="connector,fast,pdfminer,ocr"

say() { printf '%s\n' "$*"; }
fail() { printf '\nENLENS could not be installed: %s\n' "$*" >&2; exit 1; }

case "$VERSION" in
  @*) [ -n "${ENLENS_WHEEL:-}" ] || fail "this copy of install.sh does not name a version. Use the one from a GitHub Release: https://github.com/$REPO/releases" ;;
esac
command -v curl >/dev/null 2>&1 || fail "the program curl is missing."

tmp="$(mktemp -d 2>/dev/null || mktemp -d -t enlens)"
trap 'rm -rf "$tmp"' EXIT INT TERM

# 1. uv ---------------------------------------------------------------------------------------
find_uv() {
  for c in "$(command -v uv 2>/dev/null || true)" "${XDG_BIN_HOME:-}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -n "$c" ] && [ -x "$c" ] && [ ! -d "$c" ]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}
UV="$(find_uv || true)"
if [ -z "$UV" ]; then
  say "1/4  Getting uv, which installs ENLENS and its own Python…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >"$tmp/uv.log" 2>&1 || { cat "$tmp/uv.log" >&2; fail "uv could not be installed."; }
  UV="$(find_uv || true)"
  [ -n "$UV" ] || fail "uv was installed, but cannot be found. Open a new Terminal window and run the line again."
else
  say "1/4  uv is here already ($UV)."
fi

# 2. the package --------------------------------------------------------------------------------
if [ -n "${ENLENS_WHEEL:-}" ]; then
  [ -f "$ENLENS_WHEEL" ] || fail "no such file: $ENLENS_WHEEL"
  WHEEL="$(basename "$ENLENS_WHEEL")"
  cp "$ENLENS_WHEEL" "$tmp/$WHEEL"
  say "2/4  Using the package $WHEEL."
else
  WHEEL="enlens_claims-$VERSION-py3-none-any.whl"
  BASE="https://github.com/$REPO/releases/download/v$VERSION"
  say "2/4  Downloading ENLENS $VERSION…"
  curl -fsSL -o "$tmp/$WHEEL" "$BASE/$WHEEL" || fail "the download of $BASE/$WHEEL did not work. Are you online?"
  curl -fsSL -o "$tmp/SHA256SUMS" "$BASE/SHA256SUMS" || fail "the checksums of the release could not be downloaded."
  want="$(awk -v f="$WHEEL" '$2 == f || $2 == "*" f { print $1 }' "$tmp/SHA256SUMS")"
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$tmp/$WHEEL" | awk '{print $1}')"
  else got="$(shasum -a 256 "$tmp/$WHEEL" | awk '{print $1}')"; fi
  [ -n "$want" ] && [ "$want" = "$got" ] || fail "the downloaded package does not match the release's checksum (nothing was installed). Try again later."
fi

# 3. install ------------------------------------------------------------------------------------
say "3/4  Installing ENLENS (the first time this also fetches Python 3.12; a minute or two)…"
UV_PYTHON_PREFERENCE=only-managed "$UV" tool install --force --quiet --python 3.12 \
  "enlens-claims[$EXTRAS] @ file://$tmp/$WHEEL" || fail "uv could not install ENLENS (see the lines above)."
BIN="$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$HOME/.local/bin")"
[ -x "$BIN/enlens" ] || fail "ENLENS was installed, but $BIN/enlens is missing."

# 4. the icon, the Claude Code plugin, and open ---------------------------------------------------
say "4/4  Making the ENLENS icon…"
set -- post-install --by script
if [ -n "${ENLENS_HOME:-}" ]; then set -- "$@" --home "$ENLENS_HOME"; fi
if [ -z "${ENLENS_NO_OPEN:-}" ]; then set -- "$@" --open; fi
"$BIN/enlens" "$@" || fail "the last step did not work (see above)."

say ""
say "Done. Next time, open ENLENS from its icon. To update it later, run the same line again."
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "(In a terminal, ENLENS's commands are in $BIN, for example: $BIN/enlens update)" ;;
esac
