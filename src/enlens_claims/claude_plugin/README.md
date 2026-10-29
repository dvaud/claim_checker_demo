# ENLENS for Claude Code

This plugin lets Claude Code, signed in with your own Claude plan, do the reading for ENLENS: profile labels, concept
links, theme names, references, search words and checks. ENLENS keeps your documents, results and reviews on your
computer and checks every quote; only the passages inside the tasks Claude Code takes are sent to Anthropic.

## Set it up (once)

1. In ENLENS: Settings, AI model service, choose **Claude Code (your subscription)** and confirm.
2. In a terminal: `enlens claude-setup`. It prepares this plugin in your ENLENS folder, checks that the ENLENS
   connector starts, and prints two lines.
3. Type those two lines (they add the plugin to Claude Code):

   ```
   claude plugin marketplace add "<your ENLENS folder>/claude-plugin"
   claude plugin install enlens-run@enlens
   ```

   Inside Claude Code the same works as `/plugin marketplace add …` and `/plugin install enlens-run@enlens`.
4. Restart Claude Code. The first time it starts the ENLENS connector it may ask you to allow it.

## Use it

Press an AI button in ENLENS (Label with the AI, Ask the AI to relate them, Name the themes, Check…). The page says
what waits, for example *Waiting for Claude Code: 120 passages to label*. Then, in Claude Code, opened in any folder:

```
/enlens-run Pilot              # every kind of task waiting in the project Pilot
/enlens-run Pilot label        # only the labels
/enlens-run Pilot --parallel 4 # four helpers at the same time (faster, uses your plan's limit faster)
```

Each kind of task goes to a helper on the model ENLENS names for it: labels and links on Haiku, theme names,
references and search words on Sonnet, checks on Opus. Unsure answers go once to a stronger model. You follow the
progress in the ENLENS app.

A run can stop at any moment (a usage limit, a closed laptop, Ctrl+C): a batch handed out and not answered returns to
the queue after 30 minutes, and the next `/enlens-run` continues where it stopped.

## What it can do

The helpers can use only the ENLENS queue tools: they read nothing but the passages the queue hands them and write
nothing but answers. ENLENS never handles your login and never runs on anyone else's plan. When you press
*Start Claude Code* in the app, ENLENS starts Claude Code for you with only the ENLENS queue tools allowed.
