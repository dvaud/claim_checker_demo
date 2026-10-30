// First run. When the AI model is already set up (someone installed the app), the user starts by naming a project
// and adding documents. The model step appears only when no model works yet.
import { App, api, h, icon, replace, clear, toast, showError, field, navigate, store } from "../lib.js";
import { testResult, plainTestResult, claudeSetupCard } from "./settings.js";
import { linkProjectDialog, importProjectDialog } from "./projects.js";

function rerender() { window.dispatchEvent(new HashChangeEvent("hashchange")); }

export async function renderSetup(view) {
  const hasProject = (App.state.projects || []).length > 0;
  const s = App.settings();
  const cc = s.backend === "claude_code";
  // 0.9: subscription first: a new installation answers with Claude Code; the first step sets it up (or skips it)
  const modelOk = cc ? store("setup-ai") === "done" : App.modelConfigured();
  const stepsAll = modelOk ? [["Project", "project"], ["Documents", "docs"]] : [["AI", "model"], ["Project", "project"], ["Documents", "docs"]];
  const current = !modelOk ? "model" : !hasProject ? "project" : "docs";
  const idx = stepsAll.findIndex((x) => x[1] === current);

  const steps = h("ol", { class: "setup-steps", "aria-label": "Steps" },
    stepsAll.map(([t, key], i) => h("li", { class: `setup-step ${i === idx ? "active" : i < idx ? "done" : ""}`, "aria-current": i === idx ? "step" : null }, h("span", { class: "n" }, i < idx ? icon("check", { size: 12 }) : String(i + 1)), t)));
  const wrap = h("div", { class: "setup" },
    h("div", { class: "hero" }, h("p", { class: "eyebrow" }, "Welcome"), h("h1", { id: "page-title", tabindex: "-1" }, "Explore your documents, and check what they say"),
      h("p", {}, "ENLENS reads your reports, papers and interview notes. Search them, see which topics and codes each one addresses, follow concepts and themes across them, and check a hypothesis against them, with the exact quotes so you can judge for yourself."),
      modelOk && !cc ? h("p", { class: "it small", style: { color: "var(--ok)" } }, icon("house", { size: 14 }), h("span", {}, "The AI model is set up and runs on this computer: your documents never leave it.")) : null),
    steps);
  view.appendChild(wrap);
  const body = h("div", {});
  wrap.appendChild(body);

  if (current === "model") { if (cc) claudeStep(body); else await modelStep(body); }
  else if (current === "project") projectStep(body);
  else sourcesStep(body);
}

function claudeStep(body) {
  const next = () => { store("setup-ai", "done"); rerender(); };
  const nextBtn = h("button", { class: "btn btn-lg", type: "button", onClick: next }, "Next: your project", icon("arrow-right", { size: 14 }));
  replace(body, h("div", { class: "card" }, h("h2", {}, "The AI: Claude, on your own Claude plan"),
    h("p", { class: "muted" }, "ENLENS uses Claude Code, signed in with your Claude subscription, for the AI parts (labels, theme names, checks). Search, keyword profiles, the glossary and themes work without any AI. Your documents stay on this computer; only the passages inside the AI's tasks are sent to Anthropic."),
    claudeSetupCard({ onReady: () => { nextBtn.classList.add("btn-primary"); } }),
    h("div", { class: "btn-row", style: { marginTop: "14px" } }, nextBtn),
    h("details", { class: "fold", style: { marginTop: "10px" } }, h("summary", {}, "No Claude plan? Other options"),
      h("div", { class: "stack", style: { marginTop: "8px" } },
        h("p", { class: "small" }, h("strong", {}, "A model on this computer"), " (Ollama, LM Studio…): free and fully private. ",
          h("button", { class: "btn btn-sm", type: "button", onClick: async () => { try { await api("PUT", "/api/settings", { backend: "auto" }); await App.refresh(); rerender(); } catch (e) { showError(e); } } }, "Use a local model")),
        h("p", { class: "small" }, h("strong", {}, "No AI for now"), ": everything that needs no AI works; AI buttons use a simple word-overlap stand-in. ",
          h("button", { class: "btn btn-sm", type: "button", onClick: async () => { try { await api("PUT", "/api/settings", { backend: "baseline" }); await App.refresh(); toast("Demo mode selected. Change it any time in Settings → AI.", "ok"); rerender(); } catch (e) { showError(e); } } }, "Continue without AI"))))));
}

function projectStep(body) {
  const input = h("input", { class: "input", type: "text", placeholder: "e.g. Remote work literature", autocomplete: "off", maxlength: 60, id: "proj-name" });
  const err = h("div", { class: "field-error", role: "alert" });
  const btn = h("button", { class: "btn btn-primary btn-lg", type: "submit" }, "Create the project", icon("arrow-right", { size: 14 }));
  const form = h("form", { onSubmit: async (e) => {
    e.preventDefault();
    err.textContent = "";
    if (!input.value.trim()) { input.focus(); return; }
    btn.disabled = true;
    try {
      const typed = input.value.trim();
      const r = await api("POST", "/api/projects", { name: typed });
      await App.refresh();
      if (r.project.name !== typed) toast(`Saved as “${r.project.name}” (some characters can't be used in a project name). Now add your documents.`, "warn", { ttl: 9000 });
      else toast(`Project “${r.project.name}” created. Now add your documents.`, "ok");
      navigate("#/sources");
    } catch (ex) { err.textContent = ex.message; btn.disabled = false; }
  } },
    h("div", { class: "field" }, h("label", { class: "field-label", for: "proj-name" }, "Project name"), input, h("div", { class: "field-help" }, "A project is one set of documents you explore together (and the hypotheses you check against them), for example one literature review. You can make more later.")),
    err,
    h("div", { class: "btn-row" }, btn, h("button", { class: "btn btn-ghost", type: "button", onClick: () => linkProjectDialog() }, "Open an existing ENLENS project folder (advanced)")));
  // 0.10: a new computer can take everything from the old one instead
  const moving = h("div", { class: "card card-plain move-in" }, h("div", { class: "it" }, icon("monitor", { size: 16 }), h("strong", {}, "Used ENLENS on another computer?")),
    h("p", { class: "muted small" }, "Bring all your projects and settings here in one go, from the file made with “Move ENLENS to another computer” on the old one."),
    h("button", { class: "btn btn-sm", type: "button", onClick: () => importProjectDialog({ move: true }) }, icon("upload", { size: 13 }), "Import from another computer"));
  replace(body, h("div", { class: "card" }, h("h2", {}, "Give your project a name"), form), moving);
  setTimeout(() => input.focus(), 50);
}

function sourcesStep(body) {
  replace(body, h("div", { class: "card" }, h("h2", {}, "Add your documents"), h("p", { class: "muted" }, `Project “${App.project}” is ready. Add the reports, papers and web pages you want to explore: PDF, Word, text, Markdown or saved web pages (HTML).`),
    h("div", { class: "btn-row" }, h("a", { class: "btn btn-primary btn-lg", href: "#/sources" }, icon("upload", { size: 15 }), "Add documents"), h("a", { class: "btn btn-ghost", href: "#/overview" }, "Skip for now"))));
}

async function modelStep(body) {
  const s = App.settings();
  replace(body, h("div", { class: "card" }, h("h2", {}, "Set up the AI model"), h("p", { class: "muted" }, "Looking for AI model services on this computer…")));
  let servers = [];
  try { servers = (await api("GET", "/api/servers")).servers || []; } catch (_) { servers = []; }
  clear(body);
  const card = h("div", { class: "card" }, h("h2", {}, "Set up a model on this computer"), h("p", { class: "muted" }, "This is the technical part. It is done once, usually by whoever installs the app. If that is not you, ask them; the steps are below."),
    App.state.local_only ? null : h("p", { class: "small" }, "Have a Claude plan? ", h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async () => { try { await api("PUT", "/api/settings", { backend: "claude_code", allow_claude_code: true }); await App.refresh(); rerender(); } catch (e) { showError(e); } } }, "Use Claude Code instead")));
  body.appendChild(card);

  if (!servers.length) {
    card.appendChild(h("div", { class: "notice notice-warn", style: { margin: "12px 0" } }, icon("alert-triangle"), h("div", {}, h("p", {}, h("strong", {}, "No AI model service is running on this computer.")), h("p", {}, "The easiest one is Ollama, a free program that runs AI models on your own computer:"))));
    card.appendChild(h("div", { class: "guide" },
      h("div", { class: "guide-step" }, h("span", { class: "n" }, "1"), h("div", {}, "Install Ollama from ", h("strong", {}, "ollama.com"), " and start it.")),
      h("div", { class: "guide-step" }, h("span", { class: "n" }, "2"), h("div", {}, "Download a model. In a terminal window, type: ", h("code", {}, "ollama pull qwen3:8b"), h("div", { class: "muted small" }, "About 5 GB. Larger models judge better but need more memory and time."))),
      h("div", { class: "guide-step" }, h("span", { class: "n" }, "3"), h("div", {}, "Optional, for search by meaning (finding excerpts that use other words): ", h("code", {}, "ollama pull nomic-embed-text"))),
      h("div", { class: "guide-step" }, h("span", { class: "n" }, "4"), h("div", {}, "Come back here and ", h("button", { class: "btn btn-sm", type: "button", onClick: () => location.reload() }, icon("refresh", { size: 13 }), "look again")))));
    card.appendChild(h("p", { class: "muted small" }, "LM Studio, llama.cpp, Jan or vLLM work too: start one with a model loaded, then look again."));
    const alt = h("details", { class: "fold" }, h("summary", {}, "Other options: the Claude API, or trying the app without an AI"),
      h("div", { class: "stack", style: { marginTop: "8px" } },
        h("div", { class: "cloud-box" }, h("p", { style: { color: "inherit", margin: 0 } }, h("strong", {}, "Claude API (cloud).")), h("p", {}, "Excerpts of your documents are sent to Anthropic's servers. Needs an account key and an explicit opt-in."), h("a", { class: "btn btn-sm", href: "#/settings/model", style: { marginTop: "8px" } }, "Set up in Settings → Advanced")),
        h("div", { class: "notice" }, icon("cpu"), h("div", {}, h("p", {}, h("strong", {}, "Demo mode"), " uses a simple word-overlap stand-in instead of an AI. Good for seeing how the app works; its results are not findings."),
          h("button", { class: "btn btn-sm", type: "button", onClick: async () => { try { await api("PUT", "/api/settings", { backend: "baseline" }); await App.refresh(); toast("Demo mode selected.", "ok"); rerender(); } catch (e) { showError(e); } } }, "Use demo mode")))));
    card.appendChild(alt);
    return;
  }

  const srv = servers.find((x) => x.kind === "ollama") || servers[0];
  const serverSel = h("select", { class: "select" }, servers.map((x, i) => h("option", { value: String(i), selected: x === srv }, x.kind === "ollama" ? `Ollama ${x.version || ""} at ${x.url}` : `OpenAI-compatible server at ${x.url}`)));
  const chatSel = h("select", { class: "select" });
  const embSel = h("select", { class: "select" });
  const fill = () => {
    const sv = servers[Number(serverSel.value)];
    replace(chatSel, (sv.chat_models || []).map((m) => h("option", { value: m, selected: m === s.ollama_model || m === s.openai_model }, m)));
    if (!(sv.chat_models || []).length) chatSel.appendChild(h("option", { value: "" }, "no chat model installed"));
    replace(embSel, h("option", { value: "" }, "None (search by words only)"), (sv.embedding_models || []).map((m) => h("option", { value: m, selected: m === s.embed_model }, m)));
  };
  serverSel.addEventListener("change", fill); fill();
  const out = h("div", { "aria-live": "polite" });
  const testBtn = h("button", { class: "btn btn-primary", type: "button" }, icon("zap", { size: 14 }), "Save and test");
  const next = h("button", { class: "btn btn-primary", type: "button", hidden: true, onClick: () => rerender() }, "Next: your project", icon("arrow-right", { size: 14 }));
  testBtn.addEventListener("click", async () => {
    const sv = servers[Number(serverSel.value)];
    if (!chatSel.value) { toast("No AI model is installed on this service. In a terminal: ollama pull qwen3:8b", "warn"); return; }
    const changes = sv.kind === "ollama" ? { backend: "ollama", ollama_url: sv.url, ollama_model: chatSel.value } : { backend: "openai", openai_url: sv.url, openai_model: chatSel.value };
    changes.embed_backend = embSel.value ? (sv.kind === "ollama" ? "ollama" : "openai") : "off";
    changes.embed_model = embSel.value || "";
    changes.embed_url = "";
    testBtn.disabled = true;
    replace(out, h("div", { class: "notice" }, h("span", { class: "spinner" }, icon("loader")), h("p", {}, "Testing…")));
    try {
      await api("PUT", "/api/settings", changes);
      await App.refresh();
      const r = await api("POST", "/api/servers/test");
      replace(out, plainTestResult(r));
      if (r.model_available) { next.hidden = false; next.focus(); }
    } catch (e) { replace(out, h("div", { class: "notice notice-error" }, icon("alert-circle"), h("div", {}, h("p", {}, "The AI model did not answer."), h("details", { class: "fold" }, h("summary", {}, "Technical details"), h("div", { class: "mono small" }, e.message))))); }
    testBtn.disabled = false;
  });
  card.append(
    h("div", { class: "notice notice-ok", style: { margin: "10px 0 14px" } }, icon("house"), h("p", {}, `Found ${servers.length} AI model ${servers.length === 1 ? "service" : "services"} on this computer. With a model on your own computer nothing leaves it.`)),
    field("Service", serverSel),
    h("div", { class: "fields-2" }, field("AI model that reads and judges", chatSel, { help: "A model of 8 billion parameters (“8b”) or more judges noticeably better." }), field("Model for search by meaning (optional)", embSel, { help: "Finds excerpts even when they use other words than the hypothesis." })),
    h("div", { class: "btn-row" }, testBtn, next, h("a", { class: "btn btn-ghost", href: "#/settings/model" }, "More options")),
    out);
}

export { testResult };
