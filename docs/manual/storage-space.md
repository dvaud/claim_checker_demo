[Manual](../MANUAL.md) › [Work together](together.md) › A storage space of your team's own

# A storage space of your team's own

> **In short**
> - A private storage space online, free at a team's size, at Backblaze (most research groups) or Cloudflare (large
>   teams that grow quickly). ENLENS fills and reads it by itself; nobody installs anything or looks for a folder.
> - The owner sets it up once, on the *Team page* (*Manage the team* in the project menu), in about five minutes;
>   colleagues join from a link, with *Join a team…* in the project menu.
> - Everything is locked on your computer before it leaves it: the storage company cannot read your work.
> - The owner can remove a colleague (their keys stop working) or move the team to another storage space.

Your team rents a private storage space at a company that keeps files online (technically an *S3 bucket*), free at a
team's size. ENLENS puts what you share there and brings in what your colleagues share, by itself, about every ten
minutes and soon after you share something: nobody installs a sync app or looks for a folder. Everything is locked on
your computer before it leaves it ([what the storage holds](privacy.md#through-a-storage-space-of-your-teams-own-0180rc2)).

## Which company

Two are built in, each free up to 10 GB (a corpus of a few hundred PDFs is 1 to 3 GB):
- **Backblaze**, for most research groups: no card, storage in the EU, and each colleague's key can write only in
  their own part of the space.
- **Cloudflare**, for large teams that grow quickly: fetching is always free, so many colleagues joining costs
  nothing; it asks for a card when you switch its storage on (nothing is charged within the free amount).

## Setting it up (the owner, once, about five minutes)

Open the project menu at the top of the sidebar and choose *Manage the team* (or press *Set up a team* in the *Team*
tab): that is the Team page. Under *A storage space (recommended)* choose *Backblaze…* or *Cloudflare…*. The dialog
walks you through it:
- *Backblaze:* make a free account (paste the address in your browser; choose **EU Central** as the region on the
  sign-up form: it cannot be changed later; if Backblaze's *Not so fast!* page keeps asking whether you are a robot, see
  below), open *Application Keys*, choose *Generate New Master Application Key*, and paste its *keyID* and
  *applicationKey*. ENLENS checks where the storage is (and says so when it is not in the EU), makes a key of its own
  with only the rights it needs, forgets the one you pasted, makes a private storage space and tries it. Afterwards,
  generate a new master key in Backblaze: that makes the pasted one useless.
- *Cloudflare:* make an account (paste `dash.cloudflare.com/sign-up` in your browser), switch *R2 Object Storage* on,
  tick *I am signed in*, open *Make the token ENLENS needs*, choose *Create Token*, and paste the token. ENLENS makes a
  storage space in Cloudflare's EU area and tries it.

If the company says it is down for maintenance, try again later: nothing is set up until the end.

The dialog gives each company's sign-up address with a *Copy* button rather than a link, so you choose the browser.
If Backblaze's sign-up page keeps showing *Not so fast!* and the *I'm not a robot* box comes back each time you tick
it, its check does not work in that browser: strict tracking protection, a privacy browser (Firefox's strictest
setting, Brave, Zen, LibreWolf) or a VPN can cause it. Paste the address in another browser, such as Safari, Chrome
or Edge, and open *Application Keys* there too, where you are signed in.

## Inviting a colleague

On the Team page, *Invite a colleague…* (under *The storage space*, in the owner's copy) makes a message with a link (it
starts with `enlens://join#`). Send it privately: it holds the keys to your storage space. The colleague opens ENLENS
and chooses *Join a team…* in the project menu (also a button on the *Projects* page, and *Join with the invite link…*
under *Invited to a team?* when ENLENS is first set up), pastes the link, and ENLENS makes a new project for it. A copy
they already have can use *Join with an invite link…* in its *Team* tab instead. Their first rounds bring the documents
and everything shared; you see them under *People* on the Team page once your ENLENS has let them in, which it does by
itself at its next round; until they have sent anything they are listed as *nothing sent yet*. A link works once;
*Withdraw* takes back one not used yet.

## On the Team page

The Team page is where the team itself is managed; the *Team* tab keeps only the day-to-day (what waits for your word,
*Sync now*, what came in), with one quiet line, such as *Backblaze · 3 people · Manage the team*, that opens the page.
The card *The storage space* says where the space is and the invites not used yet; *People* lists everyone in it. The
owner's copy keeps the space's keys (*keeps the space's keys*); when the project's owner changes, the keys go to the new
owner's copy by themselves. The storage account itself stays the person's who made it, who can always reach the space
through the service's website: for a hand-over in full, the new owner moves the team to a storage space of their own
(below). The owner can also:
- **Remove** a colleague (*More* on their row under *People*; the copy that keeps the space's keys offers *Remove from
  the team…*): their keys stop working, and the project's key is replaced for everyone else, so what is written
  afterwards does not open for them. What they shared before stays in the project.
- **Move to another storage space** (a fold on the card *The storage space*), when the space is lost, unpaid or should
  change: set up a new one; every copy writes what it shares there once more, and your colleagues' copies follow by
  themselves. When the old space cannot be reached any more, send them new invites.

A file in the space that its part's member did not sign (someone wrote in another person's name) is *set aside*: it
never comes into your project, and the card says so (more under *Technical details*).

**Stop using the storage space here** (the last card of the Team page, *Leave the storage space*) stops this copy and
forgets its keys; nothing in the space is removed. To come back, ask the owner for a new invite.

The same rules as with a shared folder decide how your copies come together: [Work together](together.md#how-two-copies-come-together).
