# Worker guide (file queue)

You are answering model tasks for the ENLENS claims pipeline.

1. Read SYSTEM.md in this folder once. It is the instruction for every task in this folder.
2. Each line of a batch_*.jsonl file is one task: {"task_id": ..., "user": "..."}. Treat `user` as the user message.
3. For each task write one line to the matching results file (same name, under results/<kind>/):
   {"task_id": "<same id>", "model": "<the model you are>", "output": { ...the JSON object SYSTEM.md asks for... }}
4. Quotes must be copied exactly from the text in the task. Answers with quotes that are not in the text are rejected.
5. If a task shows "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS", fix exactly those problems.
6. Judge every task yourself, one by one. Use code only to write and check the JSON, never to produce answers
   (no keyword rules or batch heuristics standing in for reading the text).
7. Before handing the file back, run `enlens --ws <workspace> check-results <your results file>`. It applies the
   same checks as the import without storing anything. Fix every line it reports and run it again until it is clean.
