### Tests

- **Each test starts with no Claude Code runs in memory.** A run of project "Q" that one test had stopped was still
  remembered by the next test of "Q" in the same worker, which then saw a stopped run instead of an idle queue (a
  macOS CI failure). The tests now clear the runs before and after each test and stop any stand-in still at work.
