"""Private until shared (0.18, roadmap L1): the endpoints of Handler for what each person shares (sharing.py). The
Team tab and the Share buttons on each item's page use them; the zip for a colleague is
`GET /api/projects/<p>/export.zip?scope=shared` (api_checks.py).

`Handler` takes this class as a base, so the names in ROUTES resolve on it."""
from __future__ import annotations

from .api_common import ApiError, _str
from .. import people, sharing


def _items(body: dict) -> list:
    got = body.get("items")
    if got is None and body.get("kind"):  # one item: {"kind", "key"}
        got = [{"kind": body.get("kind"), "key": body.get("key")}]
    if not isinstance(got, list):
        raise ApiError(400, "Send the items as {\"items\": [{\"kind\", \"key\"}]}.")
    return got


class SharingApi:
    def get_sharing(self, name, q):
        """Every item of the project and its state: `?kind=` keeps one kind, `?state=` one state."""
        out = sharing.listing(self.app.ws(name), _str(q, "kind"), _str(q, "state"))
        out["me"] = {"id": people.me(), "name": people.my_name()}
        out["kinds"] = {k: {"one": w[0], "many": w[1]} for k, w in sharing.WORDS.items()}
        return out

    def get_sharing_item(self, name, kind, key, q):
        if kind not in sharing.KINDS:
            raise ApiError(404, "No such kind of item.")
        return {"item": sharing.one(self.app.ws(name), kind, key)}

    def post_share(self, name, q):
        body = self._body()
        return sharing.share(self.app.ws(name), _items(body), str(body.get("why") or "") or None)

    def post_unshare(self, name, q):
        body = self._body()
        return sharing.unshare(self.app.ws(name), _items(body), str(body.get("why") or "") or None)
