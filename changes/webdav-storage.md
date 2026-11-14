### New

- **Your institution's drive as the team's storage space.** Besides Backblaze and Cloudflare, the Team page offers
  *Your institution's drive…*: a folder in SURFdrive, SURF Research Drive or a university's Nextcloud (any drive that
  speaks WebDAV), with nobody signing up anywhere new. The owner gives the drive's WebDAV address (a button fills in
  SURFdrive's), their user name and an app password made for ENLENS in the drive's settings (never their main
  password; it stays in the keychain). ENLENS makes a folder *ENLENS - <project>* there and tries it. Everyone in the
  team needs an account at the same drive: *Invite a colleague…* asks for their user name there and shares the folder
  with them, where the drive lets a program share (Nextcloud and ownCloud do); otherwise it says to share it in the
  drive's website. Joining asks the colleague for their own user name and app password and finds the shared folder in
  their drive, or lets them choose it. Removing a colleague stops sharing the folder with them where ENLENS can (it
  shared the folder, or knows their account and the drive lets a program share); where it cannot, a note on the card
  *The storage space* says what is left to do in the drive's website until it is done. Everything in the
  folder is locked and signed as at Backblaze and Cloudflare; as at Cloudflare, the drive cannot keep a colleague to
  their own part, so the signatures do. *A new app password for the drive* on the card *The storage space* replaces one
  the drive no longer accepts. *Move to another storage space* works to and from a drive. Changes no result.
- **Safety and economy in the drive** (review of 14 November 2026): an invite link whose drive name and address differ
  is refused; joining shows the drive's full address and, for a drive not used on this computer before (and not
  SURF's), asks the colleague to confirm it is their institution's before the app password is sent. The folder is
  shared once per user name, and stops being shared only when nobody staying uses that account. After a hand-over the
  dialogs name the person whose drive holds the folder, and the Team tab suggests moving to a folder in the new
  owner's own drive (the user names go along, so that move shares by itself). Sharing works when the WebDAV address
  points deeper than the drive's top folder; when ENLENS cannot tell where the folder is, it says to share by hand. A
  drive's answer about another folder is reported, never read as an empty folder; a name no storage takes is left out
  of a listing; a replaced file whose answer was lost counts as written; the owner's round removes old half-written
  files once a day; a copy waiting to follow a move to a drive looks for the folder by its name each round and through
  the whole drive at most every half hour. The manual says how the drive's trash bin fills with replaced files.
- **What the audit of 14 November 2026 changed in the drive.**
  - *A removal that cannot stop the sharing is not forgotten.* The removal dialog says beforehand what will happen to
    the sharing. When ENLENS cannot stop it (shared by hand with an account it does not know, a drive without a
    sharing interface, a folder in someone else's drive), a note stays on the card *The storage space* until you
    choose *It is done*, or until ENLENS sees the share gone (it looks about once an hour where it can, and stops a
    share it could not stop at first). The research log says it too. A share made in the drive's website is stopped
    by ENLENS when it knows the colleague's user name. Removing the person whose drive holds the folder now says the
    truth: the folder stays theirs, so move the team to a folder in your own drive first.
  - *A refused app password is not tried again and again.* After the drive refuses it, ENLENS asks the drive nothing
    until you enter a new one, and the card says so (*Try the same one again* lets one round try). When the drive asks
    ENLENS to slow down, the round stops and the next one tries again, or waits as long as the drive asks when that is
    short.
  - *Whose account?* Where the drive says whose account a user name is, the invite dialog shows the name (*shared with
    Carol de Vries (cdevries)*), with *Not them: withdraw the invite*; where it does not, the dialog says so.
  - *A renamed or moved folder is found again* by what it holds, every half hour, and the words for the owner's own
    folder are the owner's.
  - *An address with a user name or password in it is refused*, and never shown back.
  - *A drive without ETags*: a file written again with the same size is still seen as new.
  - The set-up form says where the app password is kept on this computer (the keychain, or a file only you can read),
    and that it opens your whole account at the drive. The manual and the privacy pages now say that ENLENS reads the
    names of the folders at the top of your drive, and what the drive's administrators see (the folder's name, with
    the project's name, and the accounts it is shared with).
- **Files deleted from a storage space are written again** (every kind: Backblaze, Cloudflare, a drive). The owner's
  copy writes the team's list of members, keys and project file again at its next round when they are missing (no
  extra requests: it reads them anyway), and each copy writes its own files again within a day; the card *The storage
  space* says files were missing and were written again. The manual asks to change nothing in the drive's folder by
  hand and to leave it out of the drive's desktop program.
- **Safer reading of a storage service's answers** (every kind): an XML answer with a DOCTYPE is refused (as the
  `.qdc` import does), and every answer is read up to a limit. An idle round of a storage space now writes nothing on
  this computer.

### Fixed

- **After *Move to another storage space*, the owner's copy could wait for ever** when a colleague's copy followed
  before the owner's next round ("The shared folder has not brought this project's own file … yet"). The project's own
  file now goes along with the move.

### Not yet done

- The drive support has not been tried with a real SURFdrive, SURF Research Drive or Nextcloud account: it was built
  against a stand-in that follows the WebDAV standard and Nextcloud's documents. Not seen on a real drive in
  particular: how it counts refused sign-ins and whether it answers a slow-down with Retry-After, whether it gives the
  account's display name when sharing, and how it names a folder with accents.
- A colleague cannot follow a move to a drive from Backblaze, Cloudflare or another drive by themselves (ENLENS knows
  no account of theirs there): their Team tab asks them for a new invite. A colleague who becomes the owner cannot
  share the drive's folder with new colleagues through ENLENS (a shared folder cannot be shared on); the person whose
  drive holds it shares it in the drive's website, or the new owner moves the team to a folder in their own drive.

### Tests

- `tests/test_webdav_storage.py` with a stand-in drive (`tests/fake_webdav.py`: WebDAV, the OCS Share API, several
  users and shares): the storage, refusals in plain words, a file written whole or not at all, set-up, invite, join,
  working together, removal, a new app password, the hand-over, and moves to and from a drive; since the review, also
  answers from another address (never followed), forged invites, unknown drives, one share per user name, the share
  path, the holder after a hand-over, the waiting copy's requests, old temporary files, and a move that puts
  `project.json` in the new space before the old one is told (also for a folder space and Backblaze); since the audit,
  removals that leave a share (by hand, after a failure, the holder), files deleted in the folder (also in a folder
  space), a refused password across rounds, a slow-down, display names, a DOCTYPE in a listing, read caps, a renamed
  folder, an address with a password, no ETags, an href as a whole address or in another Unicode form, a share for
  reading only, and an idle round's requests and writes. The stand-in now keeps a share's rights and display names.
