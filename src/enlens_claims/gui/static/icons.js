// Inline SVG icons (24×24, stroke-based). Every icon is built as DOM nodes, never from HTML strings.
const NS = "http://www.w3.org/2000/svg";

// Each entry: a list of [tag, attributes] shapes.
const ICONS = {
  check: [["path", { d: "M20 6 9 17l-5-5" }]],
  x: [["path", { d: "M18 6 6 18M6 6l12 12" }]],
  plus: [["path", { d: "M5 12h14M12 5v14" }]],
  minus: [["path", { d: "M5 12h14" }]],
  "circle-check": [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "m9 12 2 2 4-4" }]],
  "circle-x": [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "m15 9-6 6M9 9l6 6" }]],
  "circle-minus": [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M8 12h8" }]],
  "circle-half": [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M12 2a10 10 0 0 1 0 20z", fill: "currentColor", stroke: "none" }]],
  "circle-dashed": [["circle", { cx: 12, cy: 12, r: 10, "stroke-dasharray": "4.2 3.1" }]],
  "circle-dot": [["circle", { cx: 12, cy: 12, r: 10 }], ["circle", { cx: 12, cy: 12, r: 2.5, fill: "currentColor", stroke: "none" }]],
  circle: [["circle", { cx: 12, cy: 12, r: 10 }]],
  "arrows-opposed": [["path", { d: "M8 3 4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4" }]],
  "alert-triangle": [["path", { d: "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3M12 9v4M12 17h.01" }]],
  "alert-circle": [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M12 8v4M12 16h.01" }]],
  info: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M12 16v-4M12 8h.01" }]],
  help: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01" }]],
  search: [["circle", { cx: 11, cy: 11, r: 8 }], ["path", { d: "m21 21-4.3-4.3" }]],
  "search-x": [["circle", { cx: 11, cy: 11, r: 8 }], ["path", { d: "m21 21-4.3-4.3M13.5 8.5l-5 5M8.5 8.5l5 5" }]],
  "file-text": [["path", { d: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7ZM14 2v4a2 2 0 0 0 2 2h4M10 9H8M16 13H8M16 17H8" }]],
  folder: [["path", { d: "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" }]],
  "book-open": [["path", { d: "M12 7v14M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" }]],
  sliders: [["path", { d: "M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4" }]],
  highlighter: [["path", { d: "m9 11-6 6v3h9l3-3M22 12l-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4" }]],
  history: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M12 6v6l4 2" }]],
  "list-checks": [["path", { d: "m3 17 2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8" }]],
  flask: [["path", { d: "M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2M8.5 2h7M7 16h10" }]],
  play: [["path", { d: "m6 3 14 9-14 9V3z" }]],
  stop: [["rect", { x: 5, y: 5, width: 14, height: 14, rx: 2 }]],
  power: [["path", { d: "M12 2v10M18.4 6.6a9 9 0 1 1-12.77.04" }]],
  upload: [["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" }]],
  download: [["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" }]],
  trash: [["path", { d: "M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" }]],
  sun: [["circle", { cx: 12, cy: 12, r: 4 }], ["path", { d: "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" }]],
  moon: [["path", { d: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" }]],
  monitor: [["rect", { x: 2, y: 3, width: 20, height: 14, rx: 2 }], ["path", { d: "M8 21h8M12 17v4" }]],
  shield: [["path", { d: "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" }]],
  house: [["path", { d: "M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" }]],
  cloud: [["path", { d: "M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" }]],
  cpu: [["rect", { x: 4, y: 4, width: 16, height: 16, rx: 2 }], ["rect", { x: 9, y: 9, width: 6, height: 6 }], ["path", { d: "M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2" }]],
  "chevron-down": [["path", { d: "m6 9 6 6 6-6" }]],
  "chevron-up": [["path", { d: "m18 15-6-6-6 6" }]],
  "chevron-right": [["path", { d: "m9 18 6-6-6-6" }]],
  "chevron-left": [["path", { d: "m15 18-6-6 6-6" }]],
  "arrow-left": [["path", { d: "m12 19-7-7 7-7M19 12H5" }]],
  "arrow-right": [["path", { d: "M5 12h14M12 5l7 7-7 7" }]],
  link: [["path", { d: "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" }]],
  star: [["path", { d: "M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" }]],
  loader: [["path", { d: "M12 2v4M16.2 7.8l2.9-2.9M18 12h4M16.2 16.2l2.9 2.9M12 18v4M4.9 19.1l2.9-2.9M2 12h4M4.9 4.9l2.9 2.9" }]],
  eye: [["path", { d: "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" }], ["circle", { cx: 12, cy: 12, r: 3 }]],
  menu: [["path", { d: "M4 12h16M4 6h16M4 18h16" }]],
  "external-link": [["path", { d: "M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" }]],
  scale: [["path", { d: "m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1ZM2 16l3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1ZM7 21h10M12 3v18M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" }]],
  refresh: [["path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8M21 3v5h-5M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16M8 16H3v5" }]],
  key: [["path", { d: "m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4M21 2l-9.6 9.6" }], ["circle", { cx: 7.5, cy: 15.5, r: 5.5 }]],
  sparkles: [["path", { d: "M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0zM20 3v4M22 5h-4" }]],
  type: [["path", { d: "M12 4v16M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2M9 20h6" }]],
  quote: [["path", { d: "M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2zM5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z" }]],
  note: [["path", { d: "M12 20h9M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z" }]],
  split: [["path", { d: "M16 3h5v5M8 3H3v5M12 22v-8.3a4 4 0 0 0-1.172-2.872L3 3M15 9l6-6" }]],
  layers: [["path", { d: "m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83ZM2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17" }]],
  "more-horizontal": [["circle", { cx: 12, cy: 12, r: 1 }], ["circle", { cx: 19, cy: 12, r: 1 }], ["circle", { cx: 5, cy: 12, r: 1 }]],
  clock: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M12 6v6l4 2" }]],
  zap: [["path", { d: "M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z" }]],
  database: [["ellipse", { cx: 12, cy: 5, rx: 9, ry: 3 }], ["path", { d: "M3 5v14a9 3 0 0 0 18 0V5M3 12a9 3 0 0 0 18 0" }]],
  "folder-open": [["path", { d: "m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" }]],
  bug: [["path", { d: "m8 2 1.88 1.88M14.12 3.88 16 2M9 7.13v-1a3.003 3.003 0 1 1 6 0v1M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6M12 20v-9M6.53 9C4.6 8.8 3 7.1 3 5M6 13H2M3 21c0-2.1 1.7-3.9 3.8-4M20.97 5c0 2.1-1.6 3.8-3.5 4M22 13h-4M17.2 17c2.1.1 3.8 1.9 3.8 4" }]],
  // 0.7
  tag: [["path", { d: "M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z" }], ["circle", { cx: 7.5, cy: 7.5, r: 0.5 }]],
  grid: [["rect", { x: 3, y: 3, width: 7, height: 7, rx: 1 }], ["rect", { x: 14, y: 3, width: 7, height: 7, rx: 1 }], ["rect", { x: 14, y: 14, width: 7, height: 7, rx: 1 }], ["rect", { x: 3, y: 14, width: 7, height: 7, rx: 1 }]],
  network: [["circle", { cx: 18, cy: 5, r: 3 }], ["circle", { cx: 6, cy: 12, r: 3 }], ["circle", { cx: 18, cy: 19, r: 3 }], ["path", { d: "m8.59 13.51 6.83 3.98M15.41 6.51l-6.82 3.98" }]],
  shapes: [["path", { d: "M8.3 10a.7.7 0 0 1-.626-1.079L11.4 3a.7.7 0 0 1 1.198-.043L16.3 8.9a.7.7 0 0 1-.572 1.1Z" }], ["rect", { x: 3, y: 14, width: 7, height: 7, rx: 1 }], ["circle", { cx: 17.5, cy: 17.5, r: 3.5 }]],
  "text-search": [["path", { d: "M21 6H3M10 12H3M10 18H3" }], ["circle", { cx: 17, cy: 15, r: 3 }], ["path", { d: "m21 19-1.9-1.9" }]],
  copy: [["rect", { x: 9, y: 9, width: 13, height: 13, rx: 2 }], ["path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }]],
  inbox: [["path", { d: "M22 12h-6l-2 3h-4l-2-3H2" }], ["path", { d: "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" }]],
  terminal: [["path", { d: "m4 17 6-6-6-6M12 19h8" }]],
  "arrow-up": [["path", { d: "M12 19V5M5 12l7-7 7 7" }]],
  pause: [["rect", { x: 6, y: 4, width: 4, height: 16, rx: 1 }], ["rect", { x: 14, y: 4, width: 4, height: 16, rx: 1 }]],
  pin: [["path", { d: "M12 17v5M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z" }]],
};

export function icon(name, opts = {}) {
  const shapes = ICONS[name] || ICONS.circle;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", opts.size || 16);
  svg.setAttribute("height", opts.size || 16);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", opts.weight || 2);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("icon", "icon-" + name);
  if (opts.class) svg.classList.add(...opts.class.split(" "));
  for (const [tag, attrs] of shapes) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    svg.appendChild(el);
  }
  return svg;
}

// Icons for grades and statuses: always shown next to the text, never colour alone.
export const STATUS_ICON = {
  supported: "circle-check",
  partially_supported: "circle-half",
  contested: "arrows-opposed",
  contradicted: "circle-x",
  unsupported: "circle-dashed",
  no_passages: "search-x",
  not_checked: "clock",
  failed: "alert-triangle",
  uncertain: "help",
  waiting: "inbox",
};
export const GRADE_ICON = { supports: "circle-check", partially_supports: "circle-half", refutes: "circle-x", none: "circle-dashed" };
