[Manual](../MANUAL.md) › [Work together](together.md) › A storage space of your team's own

# A storage space of your team's own

> **In short**
> - A private storage space online, free at a team's size, at Backblaze (most research groups) or Cloudflare (large
>   teams that grow quickly), or a folder in your institution's drive (SURFdrive, SURF Research Drive, a university's
>   Nextcloud). ENLENS fills and reads it by itself; nobody installs anything or looks for a folder.
> - The owner sets it up once, on the *Team page* (*Manage the team* in the project menu), in about five minutes;
>   colleagues join from a link, with *Join a team…* in the project menu.
> - Everything is locked on your computer before it leaves it: the storage company cannot read your work.
> - The owner can remove a colleague (their keys stop working) or move the team to another storage space.

Your team rents a private storage space at a company that keeps files online (technically an *S3 bucket*), free at a
team's size. ENLENS puts what you share there and brings in what your colleagues share, by itself, about every ten
minutes and soon after you share something: nobody installs a sync app or looks for a folder. Everything is locked on
your computer before it leaves it ([what the storage holds](privacy.md#through-a-storage-space-of-your-teams-own-0180rc2)).

## Which company

Two companies are built in, each free up to 10 GB (a corpus of a few hundred PDFs is 1 to 3 GB):
- **Backblaze**, for most research groups: no card, storage in the EU, and each colleague's key can write only in
  their own part of the space.
- **Cloudflare**, for large teams that grow quickly: fetching is always free, so many colleagues joining costs
  nothing; it asks for a card when you switch its storage on (nothing is charged within the free amount).

Or, without a new account anywhere: **your institution's drive** (below), when everyone in the team has an account at
the same drive.

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

## Your institution's drive (SURFdrive, SURF Research Drive, a Nextcloud)

If your institution gives you a drive that speaks *WebDAV* (most do: SURFdrive and SURF Research Drive for Dutch
institutions, a university's own Nextcloud or ownCloud), the team can work in a folder there instead. Nobody signs up
anywhere, and the files stay at your institution's drive. Everyone in the team needs an account at **the same** drive.

*Setting it up (the owner):* on the Team page, under *A storage space (recommended)*, choose *Your institution's
drive…*. The dialog asks for three things:
- the drive's **WebDAV address**. For SURFdrive, press *Use SURFdrive's address*
  (`https://surfdrive.surf.nl/files/remote.php/nonshib-webdav/`). A Nextcloud shows its address in its website,
  under *Files* → *Files settings* (bottom left); it looks like `https://<host>/remote.php/dav/files/<user>/`. SURF
  Research Drive shows its own;
- your **user name** at the drive, as its settings show it (on SURFdrive it is not always your e-mail address);
- an **app password**: in the drive's settings, under *Security*, make a new app password for ENLENS (on SURFdrive it
  is called a *WebDAV password*). Never give ENLENS your main password. The app password stays on this computer, in its
  keychain (or, where there is none, in a file in ENLENS's folder that only you can read); nobody else gets it. Keep in
  mind that an app password opens **your whole account** at the drive, not only the team's folder: remove it in the
  drive's settings when you stop working with ENLENS. Type the address without your user name or password in it:
  they have fields of their own, and ENLENS refuses an address that holds them.

ENLENS checks them, makes a folder named *ENLENS - <your project>* in your drive and tries it. To choose a free name,
it reads the names of the folders at the top of your drive (only their names); a colleague's ENLENS does the same in
their drive when they join, to find the shared folder.

*What the drive's administrators see:* the folder's name, which holds the project's name (*ENLENS - <your project>*),
and the accounts it is shared with, as they see every shared folder. The files in it are locked, so they cannot read
your work. At Backblaze and Cloudflare the names are random instead.

*Inviting a colleague:* *Invite a colleague…* also asks for their **user name at the drive**. ENLENS then shares the
project's folder with them (they may read and change it, not share it on). Some drives do not let a program share
folders; then, or when you leave the user name empty, the dialog says so: share the folder with them yourself in the
drive's website, allowing them to edit. The invite link carries no password. The folder is shared once per account:
a second invite to the same user name (a colleague's second computer, or an invite made again) uses the same share.
Where the drive says whose account it is, the dialog shows that name beside the user name (*shared with Carol de Vries
(cdevries)*): check it is your colleague, since a user name typed one letter wrong can belong to someone else. If it
is not them, *Not them: withdraw the invite* stops sharing the folder with that account at once. Where the drive shows
no name, the dialog says so: check the account in the drive's website.

*Joining:* the colleague chooses *Join a team…* and pastes the link as usual. ENLENS sees that the team works in a
drive, shows the drive's full address, and asks for their own user name there and an app password they made for
ENLENS. The app password is sent to that address only. If ENLENS has not used that drive on their computer before (and
it is not one of SURF's), the dialog first asks them to confirm that it is their institution's drive: check the address
against the one the drive's settings show. A link that names one drive but points to another is refused. It finds the shared folder in
their drive by itself (a shared folder may have another name in their drive, or sit in a *Shared* folder); when it
cannot, it lists the folders at the top of their drive to choose from. If it is not there at all, the owner has not
shared it with them yet.

*Removing a colleague* stops sharing the folder with them where ENLENS can: when it shared the folder itself, or when
it knows their user name at the drive and the drive lets a program share. The removal dialog says beforehand which
it will be. Where ENLENS cannot (the folder was shared in the drive's website with an account it does not know, the
drive has no sharing interface, or the folder is in someone else's drive), the removal still goes ahead, and a note
stays on the card *The storage space* saying what is left to do, until you choose *It is done* (or, where ENLENS can
look, until it sees the share gone: it looks about once an hour). Until then the colleague can still read and write the
folder; the project's key is replaced at once, so what is shared from now on is locked against them. Removing the
person whose drive holds the folder cannot stop it being shared with them at all: it is theirs. Move the team to a
folder in your own drive first (*Move to another storage space*). As at Cloudflare, the drive cannot keep a colleague
to their own part of the folder: the signatures do (a file written in someone else's name is set aside).

*Leave the folder to ENLENS.* The folder shows up in everyone's files, in the drive's website and in the drive's
desktop program, where deleting is one click. Change nothing in it by hand, and leave it out of the desktop program's
folders to keep in step (in its settings, choose the folders it keeps in step and untick this one): ENLENS fetches what
it needs itself. If files go missing anyway, the owner's ENLENS writes the team's list of members and keys again at its
next round, and each copy writes its own files again within a day; the card *The storage space* then says files were
missing and were written again. This works the same at Backblaze and Cloudflare.

*If you rename or move the folder* in your drive, ENLENS looks for it about every half hour by what it holds (the
team's list of members), at the top of your drive and in a *Shared* folder, and uses it again once found. Deeper than
that it is not found: put it back at the top, under any name.

*Handing the project over* (*Hand over…* on the Team page) works as everywhere, but the folder stays in the drive of
the person who set it up: only they can share it with new colleagues or stop sharing it, and the dialogs then say to
ask them. To take full control, the new owner chooses *Move to another storage space* → *Your institution's drive…*:
ENLENS makes a folder in their own drive, shares it with the colleagues it knows the user names of, and takes the team
there.

*Replaced files and the drive's space:* ENLENS replaces some of its files in the folder at each round. A Nextcloud (and
SURF's drives) keeps each replaced file in the trash bin, or as an older version, of the person whose drive holds the
folder, and that counts against their storage space. The drive removes them by itself after a while (often 30 days).
To make room sooner, open the drive's website, choose *Deleted files* (bottom left in *Files*) and *Delete
permanently*. Whether replaced files are kept at all is a setting of the drive's administrators: ask your institution's
help desk if the space runs short. ENLENS also removes, once a day, the hidden half-written files (named *.enlens-…*)
that a cut-off connection can leave behind.

*When the drive refuses your app password* (it was removed, or expired), ENLENS stops asking the drive anything: a drive
that sees too many refused sign-ins from one address can slow down or block them, also for your other programs and
for colleagues in the same building. The card *The storage space* says so until you make a new app password in the
drive's settings and enter it with *Enter a new app password…*. *Try the same one again* lets the next round try once
more. When the drive asks ENLENS to slow down, the round stops and the next one tries again.

*Not tried with a real drive yet:* ENLENS's drive support was built and tested against a stand-in that follows the
WebDAV standard and Nextcloud's documents. In particular, it was not seen how a real drive counts refused sign-ins,
whether it gives the account's name when sharing, or how it names a folder whose name has accents. If something does
not work with your institution's drive, the Team tab says what the drive answered.

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

The Team page is where the team itself is managed; the *Team* tab (the *Team* row under the project's name) keeps only
the day-to-day (what waits for your word, *Sync now*, what came in), with one quiet line, such as *Backblaze · 3 people
· Manage the team*, that opens the page.
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
  themselves. When the old space cannot be reached any more, send them new invites. A move to your institution's
  drive: colleagues who already work in a drive at the same address follow with their own account once the new
  folder is shared with them (ENLENS shares it with the user names you gave at their invites); colleagues coming from
  Backblaze, Cloudflare or another drive cannot follow by themselves (ENLENS knows no account of theirs there): their
  Team tab asks them for a new invite, and yours lists their names.

A file in the space that its part's member did not sign (someone wrote in another person's name) is *set aside*: it
never comes into your project, and the card says so (more under *Technical details*).

**Stop using the storage space here** (the last card of the Team page, *Leave the storage space*) stops this copy and
forgets its keys; nothing in the space is removed. To come back, ask the owner for a new invite.

The same rules as with a shared folder decide how your copies come together: [How two copies of a project come together](how-two-copies-come-together.md).
