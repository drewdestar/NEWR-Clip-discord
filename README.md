# NEWR Clip

Clip / highlight bot for NEWR LABS. A "clip" here is a saved message,
not a voice recording: members submit text (or a message link), staff
approve it, and approved clips get posted to a highlight channel,
ranked by votes, with a Clip of the Week every Monday at 09:00 WIB.

One `/clip` group: add, list, top, random, search, vote, delete,
approve, reject, setup, weekly, leaderboard. Pending clips stay
invisible until approved, and there is no public pending list, staff
approve by clip ID.

Not live yet: no application, invite, or token exists for it. When
there is one, the token goes in `.env` and it runs with:

```bash
~/workspace/bots/ops/run-newr-clip.sh
```

It needs Server Members Intent and Read Message History (for fetching
linked messages). Data lives in `data.db` (SQLite, local).
