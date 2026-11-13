### Working together

- **Sharing is a choice you can see.** Under the title of a check, a set of themes or a codebook of your own, the
  small *Private* tag and *Share* button are now one choice: *Private* or *Shared with your team* (*Shared* while the
  project has no team). The one that holds is highlighted; press the other to change it, and taking a shared item
  back still asks first. While an item is shared, a line under the choice says where it goes (*Goes to Ben and Chloé
  at the next round*, then *Sent to your team today at 15:44*) and *See what you shared* opens the Team tab. A
  colleague's item shows whose it is and has no choice. Notes, log entries and links between terms keep *Share* and
  *Unshare* in their cards. Cannot change results.

### For developers

- `shareChoice()` and `shareWhere()` (views/share.js), `teamBrief()`, `briefOf()` and `forgetBrief()`
  (views/team-state.js); the *See what you shared* link sends `enlens-drawer` with `detail.section: "shared"`.
