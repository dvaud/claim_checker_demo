"""The format of what copies of a project exchange (0.18).

Copies of one project may run different versions of ENLENS: a release candidate beside the stable release, or a
colleague who has not updated yet. What one copy sends must be merged right by the other, so everything exchanged says
which format it is written in, and the oldest format a copy must understand to merge it right:

- `sync_format`: the format it is written in (`FORMAT` of the ENLENS that wrote it);
- `sync_needs`: the oldest format that merges it right. A newer format that only adds what an older copy can safely
  leave aside (a table it does not have, a column it ignores) keeps `sync_needs` low, so older copies go on reading it;
  a change an older copy would merge wrongly raises it, and older copies then refuse the file in words instead of
  merging it wrongly.

The numbers are not ENLENS versions: a release candidate and the stable release that share a format sync with each
other, and the app's version is only shown. What has no number was written before 0.18: format 1, which every later
copy reads.

The formats so far:
1. 0.14 to 0.17: the project zip (bundle.py) with `sync_seen`, `sync_copies` and `sync_removed`.
2. 0.18: what each person shares (`shares`, sharing.py); a zip sent to a colleague may hold only the shared items
   (`scope`: "shared"); readings of a document by another reader are known as one document (`documents.old_fps`);
   codebooks keep the state of each code as it was exchanged (`sync_seen` kind "code"). A copy on format 1 merges such
   a zip without harm (it leaves the new table aside), so a zip still needs only format 1. The shared folder's bundles
   (sync/folder.py) are format 2 and need it: a copy before 0.18 cannot read them.
3. 0.18 with one owner and several collaborators (L2, ownership.py): who the owner is, proposals, the owner's
   decisions and the documents as accepted (`ownership`, `proposals`, `decisions`, `canon`, merged by their own rules,
   sync/owner_merge.py), and `block_choices` no longer merged row by row. The shared folder's bundles need format 3: a
   copy with the shared folder but without these rules (format 2) stops at them in words instead of merging rows it
   does not understand. A zip still needs only format 1: an older copy leaves the four tables aside. A file of format
   2 or older comes from a copy that cannot propose: the documents it brings are this copy's to propose (or, in the
   owner's copy, the owner's own).
"""
from __future__ import annotations

FORMAT = 3          # what this ENLENS writes
ZIP_NEEDS = 1       # the oldest format that merges a project zip of this ENLENS right (see above)


def stamp(needs: int = ZIP_NEEDS) -> dict:
    """What a file says about its format, to write beside what it says about itself."""
    return {"sync_format": FORMAT, "sync_needs": max(1, int(needs))}


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def of(meta: dict | None) -> tuple[int, int]:
    """(the format a file is written in, the oldest format that merges it right). A file from before 0.18 says
    neither: format 1."""
    meta = meta if isinstance(meta, dict) else {}
    written = _int(meta.get("sync_format")) or 1
    needs = _int(meta.get("sync_needs"))
    return written, max(1, needs if needs is not None else written)


def problem(meta: dict | None, what: str = "This file", then: str = "then bring it in again") -> str | None:
    """Why this copy must not merge what `meta` describes, in words for a researcher; None when it can. `then`: what
    happens after the update (the shared folder brings it in by itself)."""
    _written, needs = of(meta)
    if needs <= FORMAT:
        return None
    version = (meta or {}).get("version")
    made = f"a newer ENLENS ({version})" if version else "a newer ENLENS"
    return (f"{what} was made with {made}, which shares work in a way this version does not know yet: bringing it in "
            f"now could merge it wrongly. Update ENLENS (Settings, Update), {then}. Nothing was changed.")
