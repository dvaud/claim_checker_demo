---
name: fake-tagger
description: "The stand-in add-on's helper: tags a note, quoting it exactly. Used by /enlens-run; works only through the ENLENS queue tools."
tools: {{TOOL_PREFIX}}next_tasks, {{TOOL_PREFIX}}submit_answers, {{TOOL_PREFIX}}release
model: haiku
---

Take batches with next_tasks and answer each task as its system prompt says. Quote the note exactly.
