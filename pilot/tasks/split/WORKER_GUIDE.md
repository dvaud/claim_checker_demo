# Worker guide (file queue)

You are answering model tasks for the ENLENS claims pipeline.

1. Read SYSTEM.md in this folder once. It is the instruction for every task in this folder.
2. Each line of a batch_*.jsonl file is one task: {"task_id": ..., "user": "..."}. Treat `user` as the user message.
3. For each task write one line to the matching results file (same name, under results/<kind>/):
   {"task_id": "<same id>", "model": "<the model you are>", "output": { ...the JSON object SYSTEM.md asks for... }}
4. Quotes must be copied exactly from the text in the task. Answers with quotes that are not in the text are rejected.
5. If a task shows "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS", fix exactly those problems.
