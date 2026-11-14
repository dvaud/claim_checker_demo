### New

- **Your institution's drive as the team's storage space.** Besides Backblaze and Cloudflare, the Team page offers
  *Your institution's drive…*: a folder in SURFdrive, SURF Research Drive or a university's Nextcloud (any drive that
  speaks WebDAV), with nobody signing up anywhere new. The owner gives the drive's WebDAV address (a button fills in
  SURFdrive's), their user name and an app password made for ENLENS in the drive's settings (never their main
  password; it stays in the keychain). ENLENS makes a folder *ENLENS - <project>* there and tries it. Everyone in the
  team needs an account at the same drive: *Invite a colleague…* asks for their user name there and shares the folder
  with them, where the drive lets a program share (Nextcloud and ownCloud do); otherwise it says to share it in the
  drive's website. Joining asks the colleague for their own user name and app password and finds the shared folder in
  their drive, or lets them choose it. Removing a colleague stops sharing the folder with them. Everything in the
  folder is locked and signed as at Backblaze and Cloudflare; as at Cloudflare, the drive cannot keep a colleague to
  their own part, so the signatures do. *A new app password for the drive* on the card *The storage space* replaces one
  the drive no longer accepts. *Move to another storage space* works to and from a drive. Changes no result.

### Fixed

- **After *Move to another storage space*, the owner's copy could wait for ever** when a colleague's copy followed
  before the owner's next round ("The shared folder has not brought this project's own file … yet"). The project's own
  file now goes along with the move.

### Not yet done

- The drive support has not been tried with a real SURFdrive, SURF Research Drive or Nextcloud account: it was built
  against a stand-in that follows the WebDAV standard and Nextcloud's documents.
- A colleague cannot follow a move to a drive from Backblaze, Cloudflare or another drive by themselves (ENLENS knows
  no account of theirs there): their Team tab asks them for a new invite. A colleague who becomes the owner cannot
  share the drive's folder with new colleagues through ENLENS (a shared folder cannot be shared on); the folder's
  owner shares it in the drive's website.

### Tests

- `tests/test_webdav_storage.py` with a stand-in drive (`tests/fake_webdav.py`: WebDAV, the OCS Share API, several
  users and shares): the storage, refusals in plain words, a file written whole or not at all, set-up, invite, join,
  working together, removal, a new app password, the hand-over, and moves to and from a drive.
