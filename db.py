"""SQLite persistence for NEWR Clip. No secrets are stored here.

Tables:
  settings     (guild_id, key, value) — staff config.
               Key: highlight_channel (text channel id for approved
               clips and the weekly highlight post).
  clips        (id, guild_id, submitted_by, original_author_id,
                text, image_url, source_link, status, channel_id,
                message_id, created_at, approved_at)
               — status is 'pending', 'approved', or 'rejected'.
               Approved clips are the only ones listed, ranked,
               searched, voted on, or posted to the highlight channel.
               Rejected clips are deleted by /clip reject, not kept,
               so no 'rejected' row normally survives; the status
               value exists for completeness.
               Clips are NOT anonymous: submitted_by is stored so
               the owner can delete their own clip and so
               /clip leaderboard can rank submitters. This is
               deliberate and different from Social's confessions.
  votes        (clip_id, guild_id, user_id)
               — one row per (clip, user): a user can vote on a
               given clip at most once (PRIMARY KEY enforces it).
  weekly_posts (guild_id, week_start, clip_id, posted_at)
               — one weekly highlight post per guild per ISO week,
               so the Monday loop and a manual /clip weekly cannot
               double-post the same week.

DB_PATH env var overrides the default data.db next to this file.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get(
    "DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings(
            guild_id INTEGER, key TEXT, value TEXT,
            PRIMARY KEY (guild_id, key));
        CREATE TABLE IF NOT EXISTS clips(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            submitted_by INTEGER NOT NULL,
            original_author_id INTEGER,
            text TEXT NOT NULL,
            image_url TEXT,
            source_link TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            channel_id INTEGER,
            message_id INTEGER,
            created_at TEXT NOT NULL,
            approved_at TEXT);
        CREATE TABLE IF NOT EXISTS votes(
            clip_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (clip_id, user_id));
        CREATE TABLE IF NOT EXISTS weekly_posts(
            guild_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            clip_id INTEGER NOT NULL,
            posted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, week_start));
        """)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_setting(guild_id: int, key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO settings VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, value))


def get_setting(guild_id: int, key: str, default: str | None = None) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE guild_id=? AND key=?",
            (guild_id, key)).fetchone()
    return row["value"] if row else default


def get_int_setting(guild_id: int, key: str, default: int | None = None) -> int | None:
    raw = get_setting(guild_id, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _vote_count_sql() -> str:
    return ("(SELECT COUNT(*) FROM votes v "
            "WHERE v.clip_id = clips.id)")


def add_clip(guild_id: int, submitted_by: int,
             original_author_id: int | None, text: str,
             image_url: str | None, source_link: str | None) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO clips (guild_id, submitted_by, original_author_id, "
            "text, image_url, source_link, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (guild_id, submitted_by, original_author_id, text,
             image_url, source_link, now()))
        return cur.lastrowid


def get_clip(clip_id: int, guild_id: int) -> sqlite3.Row | None:
    with _conn() as conn:
        return conn.execute(
            f"SELECT *, {_vote_count_sql()} AS votes FROM clips "
            "WHERE id=? AND guild_id=?", (clip_id, guild_id)).fetchone()


def list_approved(guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            f"SELECT *, {_vote_count_sql()} AS votes FROM clips "
            "WHERE guild_id=? AND status='approved' "
            "ORDER BY approved_at DESC, id DESC LIMIT ?",
            (guild_id, limit)).fetchall()


def list_pending(guild_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM clips WHERE guild_id=? AND status='pending' "
            "ORDER BY id ASC LIMIT ?", (guild_id, limit)).fetchall()


def top_approved(guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            f"SELECT *, {_vote_count_sql()} AS votes FROM clips "
            "WHERE guild_id=? AND status='approved' "
            "ORDER BY votes DESC, id ASC LIMIT ?",
            (guild_id, limit)).fetchall()


def random_approved(guild_id: int) -> sqlite3.Row | None:
    with _conn() as conn:
        return conn.execute(
            f"SELECT *, {_vote_count_sql()} AS votes FROM clips "
            "WHERE guild_id=? AND status='approved' "
            "ORDER BY RANDOM() LIMIT 1", (guild_id,)).fetchone()


def search_approved(guild_id: int, query: str,
                    limit: int = 10) -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            f"SELECT *, {_vote_count_sql()} AS votes FROM clips "
            "WHERE guild_id=? AND status='approved' AND text LIKE ? "
            "ORDER BY votes DESC, id ASC LIMIT ?",
            (guild_id, "%" + query + "%", limit)).fetchall()


def vote_clip(clip_id: int, guild_id: int, user_id: int) -> str:
    """Vote once per user per clip.

    Returns 'voted', 'already', 'not_found' (missing or guild
    mismatch), or 'not_approved' (pending clip cannot be voted on).
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT status FROM clips WHERE id=? AND guild_id=?",
            (clip_id, guild_id)).fetchone()
        if row is None:
            return "not_found"
        if row["status"] != "approved":
            return "not_approved"
        try:
            conn.execute(
                "INSERT INTO votes VALUES (?, ?, ?)",
                (clip_id, guild_id, user_id))
            return "voted"
        except sqlite3.IntegrityError:
            return "already"


def delete_clip(clip_id: int, guild_id: int) -> bool:
    """Delete a clip and its votes. Returns False if not found."""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM clips WHERE id=? AND guild_id=?",
            (clip_id, guild_id))
        conn.execute("DELETE FROM votes WHERE clip_id=?", (clip_id,))
        return cur.rowcount > 0


def approve_clip(clip_id: int, guild_id: int, channel_id: int,
                 message_id: int) -> bool:
    """Mark a pending clip approved and record its highlight post."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE clips SET status='approved', channel_id=?, "
            "message_id=?, approved_at=? "
            "WHERE id=? AND guild_id=? AND status='pending'",
            (channel_id, message_id, now(), clip_id, guild_id))
        return cur.rowcount > 0


def weekly_top(guild_id: int, days: int = 7) -> sqlite3.Row | None:
    """Top approved clip from the last `days` days, by votes then oldest."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as conn:
        return conn.execute(
            f"SELECT *, {_vote_count_sql()} AS votes FROM clips "
            "WHERE guild_id=? AND status='approved' AND approved_at>=? "
            "ORDER BY votes DESC, id ASC LIMIT 1",
            (guild_id, since)).fetchone()


def weekly_already_posted(guild_id: int, week_start: str) -> bool:
    with _conn() as conn:
        return conn.execute(
            "SELECT 1 FROM weekly_posts WHERE guild_id=? AND week_start=?",
            (guild_id, week_start)).fetchone() is not None


def mark_weekly_posted(guild_id: int, week_start: str, clip_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO weekly_posts VALUES (?, ?, ?, ?)",
            (guild_id, week_start, clip_id, now()))


def leaderboard_submitters(guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
    """Submitters ranked by approved clip count, then total votes."""
    with _conn() as conn:
        return conn.execute(
            "SELECT c.submitted_by AS user_id, COUNT(*) AS clip_count, "
            "(SELECT COUNT(*) FROM votes v JOIN clips c2 ON c2.id = v.clip_id "
            " WHERE c2.guild_id=? AND c2.submitted_by = c.submitted_by "
            " AND c2.status='approved') AS total_votes "
            "FROM clips c WHERE c.guild_id=? AND c.status='approved' "
            "GROUP BY c.submitted_by "
            "ORDER BY clip_count DESC, total_votes DESC, user_id ASC LIMIT ?",
            (guild_id, guild_id, limit)).fetchall()
