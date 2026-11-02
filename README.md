# NEWR Clip

A clip/highlight Discord bot for the NEWR LABS server (guild ID
`1465422166790242377`). Members submit memorable messages as clips;
staff approve them, and approved clips are posted to a highlight
channel, ranked by votes, and highlighted weekly.

**NOT voice recording.** Discord bots cannot reliably record voice
from this VM, and this bot does not try: a "clip" here is a saved
message (typed text, or a message fetched from a message link),
optionally with an image. Nothing in this bot or README claims
voice recording.

## Slash commands only — no prefix commands

**Every user-triggered action in this bot is a Discord slash
command** (`discord.app_commands`, guild-synced to NEWR LABS only).
There is no prefix, no `command_prefix`, and no feature that
requires typing a prefix. The bot is created with
`command_prefix=None` and defines no `@commands.command` anywhere.

The only behaviour that is not a slash command is passive and
automatic — it cannot be invoked by a user typing anything:
- **Weekly highlight loop:** a daily 09:00 WIB check that posts
  only on Mondays, and only once per guild per ISO week (enforced
  in the database), so it cannot double-post with a manual
  `/clip weekly`.

## Commands: 1 top-level command, 12 subcommands

`/clip` is a single command group, so Discord counts **1
top-level slash command** (with 12 subcommands underneath), not 12.

| Command | Who | What it does |
|---|---|---|
| `/clip add <content> [image]` | Anyone | Submit a clip for staff approval. `content` is typed text, or a Discord message link (`https://discord.com/channels/<guild>/<channel>/<message>`) whose message text is fetched and clipped. Optional image attachment (image files only). A submitted clip is pending and appears nowhere public until approved. |
| `/clip list` | Anyone | Newest approved clips (up to 10). |
| `/clip top` | Anyone | Approved clips ranked by votes (up to 10). |
| `/clip random` | Anyone | One random approved clip, as a full highlight embed. |
| `/clip search <query>` | Anyone | Search approved clips by text (up to 10). |
| `/clip vote <id>` | Anyone | Vote for an approved clip. Counted once per user per clip (enforced by the `votes` PRIMARY KEY); a second vote gets an "Already voted" reply. Pending clips cannot be voted on. |
| `/clip delete <id>` | Owner or staff | Delete a clip (and its votes). Members can delete only their own clips; staff can delete any clip. |
| `/clip approve <id>` | Staff only | Approve a pending clip and post it to the highlight channel. If no highlight channel is set, or the channel is missing, approval is refused and the pending clip is kept. |
| `/clip reject <id>` | Staff only | Reject a pending clip (deletes it; rejected clips are not kept). |
| `/clip setup <channel>` | Staff only | Set the highlight channel for approved clips and weekly highlights. |
| `/clip weekly` | Staff only | Manually post this week's highlight now: the top approved clip of the last 7 days (by votes, oldest on a tie) to the highlight channel. Refuses if this ISO week was already posted, so it cannot double-post with the Monday loop. |
| `/clip leaderboard` | Anyone | Submitters ranked by approved clip count, then total votes (up to 10). |

Staff gate: guild owner, or Administrator permission, or Manage
Guild permission, or a staff role name (Founder, Executive, Admin,
Senior Mod, Moderator, Team Lead, Helper, Security, Staff, Support
— matched by name at runtime, never by hardcoded role ID). See
`staff.py` (copied from NEWR Social).

## Approval queue

A submitted clip is `pending` and appears nowhere public: it is not
in `/clip list`, `/clip top`, `/clip random`, `/clip search`, or
`/clip leaderboard`, and it cannot be voted on. Staff approve it
with `/clip approve`, which posts the highlight embed to the
highlight channel and marks it approved, or reject it with
`/clip reject`, which deletes it. There is deliberately no public
pending list and no approve/reject buttons: staff review is
slash-only, by clip ID. Note this limitation: staff currently have
no `/clip pending` list command, so they need the clip ID from the
submitter (the ephemeral confirmation shows it) or from the
database. A pending-list command is the obvious next addition if
staff want one.

## Weekly highlight

Every Monday at 09:00 WIB the loop posts the top approved clip of
the last 7 days (by votes, oldest on a tie) as a "Clip of the Week"
embed to the highlight channel. One post per guild per ISO week is
enforced by the `weekly_posts` table, so restarts and a manual
`/clip weekly` cannot duplicate it. If no highlight channel is set,
or there are no approved clips from the last 7 days, the loop skips
silently (the manual command reports the reason instead).

## What is stored — and what is not

SQLite `data.db` in the bot directory (created on first start by
`db.init_db()`), with tables: `settings` (highlight channel),
`clips`, `votes`, `weekly_posts`.

Clips are **not anonymous** (unlike Social's confessions): the
submitter's user ID is stored, shown as the submitter on the
highlight embed, used for `/clip delete` ownership, and used for
`/clip leaderboard`. No raw user tracking beyond what clips need
is stored: no message history is read or backfilled, and votes
store only (clip, user) pairs for the once-per-user rule.

## Setup

Prerequisites: Python 3.11+, a Discord application + bot for NEWR
Clip (not created by this repo — the parent supplies the token
later), and the **Server Members Intent** enabled in the Developer
Portal (used for the staff gate). Message Content Intent is **not**
needed: message-link clips are fetched via the REST API, not read
from chat.

1. Copy `.env.example` to `.env` and put the bot token in
   `DISCORD_TOKEN` (`.env` is chmod 600; never commit it, never
   paste the token in chat). `GUILD_ID` defaults to NEWR LABS
   (`1465422166790242377`). No `.env` is shipped in git, and no
   token was invented for this build.
2. Invite the bot to NEWR LABS with at least: `applications.commands`,
   Send Messages, Embed Links, View Channel, and Read Message History
   (needed to fetch linked messages), in the channels it posts to.
3. Run it (foreground, logs to `~/workspace/bots/logs/newr-clip.log`):

   ```bash
   ~/workspace/bots/ops/run-newr-clip.sh
   ```

   The script creates `~/workspace/bots/newr-clip/.venv` on first run,
   installs `requirements.txt`, refuses to start with an empty/placeholder
   token, then runs `python -u bot.py` from the bot directory. On
   ready it logs `Logged in as ...` and `Synced 1 slash commands to
   guild 1465422166790242377`. Slash commands may take a few minutes
   to appear in the client after first sync.
4. In Discord, staff run `/clip setup` to point highlights at a
   channel. Until a channel is set, `/clip approve` and
   `/clip weekly` refuse (pending clips are kept) and the Monday
   loop skips silently.

## Proxy note

Direct TLS to Discord fails from this VM, so `bot.py` passes the
same `_proxy_kwargs()` pattern as NEWR Stats / NEWR Social (proxy
from `HTTPS_PROXY`/`https_proxy`, credentials from the environment
only) to the bot constructor.

## Files

- `bot.py` — entrypoint, intents, proxy kwargs, guild-only slash sync.
- `db.py` — SQLite helpers and schema (`settings`, `clips`, `votes`, `weekly_posts`).
- `staff.py` — staff gate (permission + role-name check).
- `ui.py` — premium embeds: blurple `0x5865F2`, success `0x57F287`,
  error `0xED4245`, warning `0xFEE75C`, gold `0xF5C518` (top /
  leaderboard / weekly only); every embed carries footer
  "NEWR Clip • NEWR LABS" plus a timestamp.
- `cogs/clips.py` — the `/clip` group (all 12 subcommands) plus the
  Monday 09:00 WIB weekly highlight loop.
- `requirements.txt` — discord.py 2.7, python-dotenv, aiohttp.
- `.env.example` — token config template (`.env` itself is never committed).
