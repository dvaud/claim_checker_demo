### Working together

- **Sharing is a choice you can see.** Under the title of a check, a set of themes or a codebook of your own, the
  small *Private* tag and *Share* button are now one choice: *Private* or *Shared with your team* (*Shared* while the
  project has no team). The one that holds is highlighted; press the other to change it, and taking a shared item
  back still asks first. While an item is shared, a line under the choice says where it goes (*Goes to Ben and Chloé
  at the next round*, then *Sent to your team today at 15:44*) and *See what you shared* opens the Team tab. A
  colleague's item shows whose it is and has no choice. Notes, log entries and links between terms keep *Share* and
  *Unshare* in their cards. Cannot change results.
- **The team has its own row under the project's name.** In a project with a team, the sidebar shows *Team* and its
  state (*synced 15:44*, *syncing now…*, *3 new*, or in amber *offline*). Press it to open the Team tab beside the
  page. The *Research log* button now always opens the research log. On a phone the row is in the menu, and the
  button in the top bar says *3 new* when work came in. A project without a team looks as before. Cannot change
  results.

### For developers

- `teamLine()` (lib.js, DESIGN.md 5.1), `shareChoice()` and `shareWhere()` (views/share.js), `teamBrief()`
  (views/team-state.js); the window event `enlens-sync-state` carries the poller's state after each look, and
  `enlens-drawer` takes `detail.section`.

### Not yet done

- The team line does not yet turn amber for a question that waits for your word: it counts it in *N new*, as the
  Team tab does.
