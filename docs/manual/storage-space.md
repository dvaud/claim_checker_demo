[Manual](../MANUAL.md) › [Work together](together.md) › A storage space of your team's own

# A storage space of your team's own

> **In short**
> - A private storage space online, free at a team's size, at Backblaze (most research groups) or Cloudflare (large
>   teams that grow quickly). ENLENS fills and reads it by itself; nobody installs anything or looks for a folder.
> - The owner sets it up once, in the *Team* tab, in about five minutes; colleagues join from a link, with **Join a
>   team** under *Projects*.
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

Open the **Team** tab and choose *Backblaze…* or
*Cloudflare…* under *Work together through a storage space*. The dialog walks you through it:
- *Backblaze:* make a free account (choose **EU Central** as the region on the sign-up form: it cannot be changed
  later), open *Application Keys*, choose *Generate New Master Application Key*, and paste its *keyID* and
  *applicationKey*. ENLENS checks where the storage is (and says so when it is not in the EU), makes a key of its own
  with only the rights it needs, forgets the one you pasted, makes a private storage space and tries it. Afterwards,
  generate a new master key in Backblaze: that makes the pasted one useless.
- *Cloudflare:* make an account (type `dash.cloudflare.com/sign-up`), switch *R2 Object Storage* on, tick *I am signed
  in*, open *Make the token ENLENS needs*, choose *Create Token*, and paste the token. ENLENS makes a storage space in
  Cloudflare's EU area and tries it.

If the company says it is down for maintenance, try again later: nothing is set up until the end.

## Inviting a colleague

In the Team tab, *Invite a colleague…* makes a message with a link (it starts with
`enlens://join#`). Send it privately: it holds the keys to your storage space. The colleague opens ENLENS, chooses
**Join a team** under *Projects* (or *Join with an invite link…* in the Team tab of a copy they already have), and
pastes the link. Their first rounds bring the documents and everything shared; you see them in the Team tab once your
ENLENS has let them in, which it does by itself at its next round. A link works once; *Withdraw* takes back one not
used yet.

## In the Team tab

The *storage space* section says where the space is, who is in it and the invites waiting. The
owner's copy keeps the space's keys (*keeps the space's keys*); when the project's owner changes, the keys go to the
new owner's copy by themselves. The storage account itself stays the person's who made it, who can always reach the
space through the service's website: for a hand-over in full, the new owner moves the team to a storage space of
their own (below). The owner can also:
- **Remove** a colleague: their keys stop working, and the project's key is replaced for everyone else, so what is
  written afterwards does not open for them. What they shared before stays in the project.
- **Move to another storage space**, when the space is lost, unpaid or should change: set up a new one; every copy
  writes what it shares there once more, and your colleagues' copies follow by themselves. When the old space cannot
  be reached any more, send them new invites.

A file in the space that its part's member did not sign (someone wrote in another person's name) is *set aside*: it
never comes into your project, and the section says so.

**Stop using the storage space here** (at the foot of the Team tab) stops this copy and forgets its keys; nothing in
the space is removed. To come back, ask the owner for a new invite.

The same rules as with a shared folder decide how your copies come together: [Work together](together.md#how-two-copies-come-together).
