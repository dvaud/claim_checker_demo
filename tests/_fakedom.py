"""A small stand-in for the page's document, so Node can run lib.js's DOM helpers in a test (0.17.0).

Enough for h(), icon() and the helpers tested with it: elements, attributes, text, events that bubble, focus.
run(probe) runs a module that has `LIB` (lib.js's URL) and `key(el, name)` (a keydown on el) in scope and prints JSON.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
NODE = shutil.which("node")

FAKE_DOM = r"""
class Node {
  constructor() { this.childNodes = []; this.parentNode = null; this._ls = {}; }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { this.childNodes = this.childNodes.filter((x) => x !== c); c.parentNode = null; return c; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.childNodes = []; this.appendChild(new Text(String(v))); }
  addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); }
  removeEventListener(t, f) { this._ls[t] = (this._ls[t] || []).filter((x) => x !== f); }
  dispatchEvent(e) {
    e.target = e.target || this;
    for (let n = this; n; n = n.parentNode) { for (const f of n._ls[e.type] || []) f(e); if (e._stop) break; }
    return !e.defaultPrevented;
  }
}
class Text extends Node { constructor(t) { super(); this.data = t; } get textContent() { return this.data; } }
class Element extends Node {
  constructor(tag) {
    super(); this.tagName = tag.toUpperCase(); this.attributes = {}; this.dataset = {}; this.style = {};
    const self = this;
    this.classList = { add: (...c) => { self.className = [...new Set([...self.className.split(/\s+/).filter(Boolean), ...c])].join(" "); },
      remove: (...c) => { self.className = self.className.split(/\s+/).filter((x) => x && !c.includes(x)).join(" "); },
      contains: (c) => self.className.split(/\s+/).includes(c), toggle() {} };
  }
  get className() { return this.attributes.class || ""; }
  set className(v) { this.attributes.class = String(v); }
  get id() { return this.attributes.id || ""; }
  set id(v) { this.attributes.id = String(v); }
  get tabIndex() { return this.attributes.tabindex === undefined ? -1 : Number(this.attributes.tabindex); }
  set tabIndex(v) { this.attributes.tabindex = String(v); }
  get hidden() { return "hidden" in this.attributes; }
  set hidden(v) { if (v) this.attributes.hidden = ""; else delete this.attributes.hidden; }
  get children() { return this.childNodes.filter((c) => c instanceof Element); }
  setAttribute(k, v) {
    if (k.startsWith("data-")) this.dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = String(v);
    this.attributes[k] = String(v);
  }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  removeAttribute(k) { delete this.attributes[k]; }
  focus() { globalThis.document.activeElement = this; }
  contains(n) { for (; n; n = n.parentNode) if (n === this) return true; return false; }
  closest() { return null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  click() { this.dispatchEvent(new Event("click")); }
}
class Event { constructor(type, o = {}) { this.type = type; Object.assign(this, o); this.defaultPrevented = false; }
  preventDefault() { this.defaultPrevented = true; } stopPropagation() { this._stop = true; } }
globalThis.Node = Node; globalThis.Element = Element; globalThis.HTMLElement = Element; globalThis.Event = Event;
globalThis.document = {
  activeElement: null, body: new Element("body"), documentElement: new Element("html"),
  createElement: (t) => new Element(t), createElementNS: (_, t) => new Element(t), createTextNode: (t) => new Text(t),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {}, getElementById: () => null,
};
globalThis.window = globalThis; globalThis.location = { hash: "", pathname: "/" };
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} }; globalThis.localStorage = globalThis.sessionStorage;
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.history = { replaceState() {} };
const key = (el, k) => el.dispatchEvent(new Event("keydown", { key: k, target: el }));
"""


def run(probe: str, tmp: Path):
    f = tmp / "probe.mjs"
    f.write_text(FAKE_DOM + f"const LIB = {json.dumps((STATIC / 'lib.js').as_uri())};\n" + probe, encoding="utf-8")
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)
