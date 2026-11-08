# Security and privacy

ENLENS keeps your documents on your own computer. A problem that could expose them, or let someone else reach the
app, matters more than any other, so please report it privately and not as an ordinary issue.

## How to report

1. Open the repository on GitHub: <https://github.com/dvaud/claim_checker_demo>.
2. Choose the **Security** tab, then **Report a vulnerability** (GitHub's private vulnerability reporting).
3. Say what you saw, what you did, and which version of ENLENS (Settings, then Technical, then *Copy technical
   details*). Please do not include text from documents that must stay private.

Only the people who look after ENLENS can read a private report. You do not need to know GitHub well: the form asks
in plain words.

## What counts

- Anything that sends the text of your documents off the computer when it should not: for example a document marked
  *Only a local AI* or *No AI* that reaches Claude, or anything sent while cloud models are switched off.
- A way for a web page, or another computer, to reach the local app and read or change your projects.
- A problem in the installer or the update: a file that is not checked, a download that could be replaced.
- A key or other secret kept or shown where it should not be.

Wrong or unhelpful results, crashes and wishes are not security problems: use *Something does not work* or *An idea
or a wish* under Issues.

## Which versions get fixes

The latest release. A release candidate is fixed by the next candidate or by the release it leads to. An older
version gets the fix when you update; updating keeps your projects and results.

## What happens after a report

We aim to answer within a week, to say that the report arrived. We look at it, tell you whether we think it is a
security problem, and say how long a fix is likely to take. The fix comes out as a new release, which says what was
wrong in plain words and thanks you, unless you would rather not be named. The report stays private until the fix is
out.
