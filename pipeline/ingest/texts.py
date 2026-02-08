"""iMessage source - noise-filtered item lists."""

import os, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib'))

from utils import macos_to_datetime, datetime_to_macos
from imessage import get_connection, extract_text_from_attributed_body
from contacts import ContactResolver
from .shared import IMESSAGE_REACTION_RE, format_time_range
from .base import Source


def _build_group_chat_names(conn, resolver):
    """Build display names for group chats that lack one."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.ROWID, GROUP_CONCAT(h.id, '|||')
        FROM chat c
        JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
        JOIN handle h ON chj.handle_id = h.ROWID
        WHERE (c.display_name IS NULL OR c.display_name = '')
        GROUP BY c.ROWID
        HAVING COUNT(h.ROWID) > 1
    """)
    names = {}
    for chat_id, handles_str in cursor.fetchall():
        handles = handles_str.split("|||")
        resolved = [resolver.resolve(h.strip()) or h.strip() for h in handles]
        names[chat_id] = ", ".join(resolved)
    return names


def _fetch_messages(conn, since_dt, until_dt=None):
    cursor = conn.cursor()
    query = """
        SELECT m.text, m.is_from_me, m.date, m.attributedBody,
               h.id as handle, c.display_name as chat_name, c.ROWID as chat_rowid
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        LEFT JOIN chat c ON cmj.chat_id = c.ROWID
        WHERE ((m.text IS NOT NULL AND m.text != '')
           OR m.attributedBody IS NOT NULL)
    """
    params = []
    if since_dt:
        query += " AND m.date >= ?"
        params.append(datetime_to_macos(since_dt))
    if until_dt:
        query += " AND m.date < ?"
        params.append(datetime_to_macos(until_dt))
    query += " ORDER BY m.date DESC"
    cursor.execute(query, params)
    return cursor.fetchall()


def _group_by_person(rows, resolver, group_names):
    by_person = defaultdict(list)
    for text, is_from_me, date, attr_body, handle, chat_name, chat_rowid in rows:
        msg = text
        if (not msg or not msg.strip()) and attr_body:
            msg = extract_text_from_attributed_body(attr_body)
        if not msg:
            continue
        if IMESSAGE_REACTION_RE.match(msg.strip()):
            continue
        if chat_name and chat_name.strip():
            person = chat_name
        elif chat_rowid and chat_rowid in group_names:
            person = group_names[chat_rowid]
        else:
            person = resolver.resolve(handle) if handle else handle or "Unknown"
        sender_name = resolver.resolve(handle) if handle else handle or "Unknown"
        by_person[person].append({
            "text": msg,
            "is_from_me": bool(is_from_me),
            "timestamp": macos_to_datetime(date),
            "sender": sender_name,
        })
    return by_person


class TextsSource(Source):
    name = "texts"
    description = "iMessage history grouped by person"
    platform_required = "Darwin"

    def collect(self, since_dt, until_dt=None):
        conn = get_connection()
        resolver = ContactResolver()
        group_names = _build_group_chat_names(conn, resolver)
        rows = _fetch_messages(conn, since_dt, until_dt)
        conn.close()
        if not rows:
            return None
        by_person = _group_by_person(rows, resolver, group_names)
        if not by_person:
            return None

        lines = [f"# Texts ({format_time_range(since_dt)})"]
        sorted_people = sorted(by_person.items(), key=lambda x: -len(x[1]))

        for person, msgs in sorted_people:
            lines.append(f"\n{person} ({len(msgs)} messages):")
            for m in sorted(msgs, key=lambda m: m["timestamp"]):
                sender = "You" if m["is_from_me"] else m.get("sender", "Unknown").split()[0]
                lines.append(f"  [{m['timestamp'].strftime('%m/%d %H:%M')}] {sender}: {m['text']}")

        return "\n".join(lines)
