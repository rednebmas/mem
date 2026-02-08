"""Gmail source - noise-filtered item lists."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib'))

from google_auth import get_gmail_service
from .shared import extract_email_name, format_time_range
from .base import Source
from .. import config


class EmailSource(Source):
    name = "email"
    description = "Gmail sent threads and kept emails"

    def collect(self, since_dt, until_dt=None):
        service = get_gmail_service()
        lines = []

        # Sent emails
        messages = self._fetch_sent_messages(service, since_dt, until_dt)
        if messages:
            threads = self._collect_threads(service, messages)
            if threads:
                lines.append(f"# Email ({format_time_range(since_dt)}, {len(threads)} threads with my replies)")
                for t in threads:
                    lines.append(f'- "{t["subject"]}" (to: {t["to"]})')

        # Kept emails
        kept_label_id = self._find_kept_label_id(service)
        if kept_label_id:
            kept = self._fetch_kept_threads(service, kept_label_id)
            if kept:
                processed = self._load_processed_kept_ids()
                new_kept = [t for t in kept if t["thread_id"] not in processed]
                if new_kept:
                    user = config.get_user_name()
                    lines.append(f"\n# Email - Kept ({len(new_kept)} threads {user} chose to keep)")
                    for t in new_kept:
                        lines.append(f'- "{t["subject"]}" (from: {t["from"]})')
                    processed.update(t["thread_id"] for t in new_kept)
                    self._save_processed_kept_ids(processed)

        return "\n".join(lines) if lines else None

    def _fetch_sent_messages(self, service, since_dt, until_dt=None):
        if since_dt:
            query = f"in:sent after:{since_dt.strftime('%Y/%m/%d')}"
        else:
            query = "in:sent newer_than:7d"
        if until_dt:
            query += f" before:{until_dt.strftime('%Y/%m/%d')}"
        result = service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()
        return result.get("messages", [])

    def _get_header(self, headers, name):
        for h in headers:
            if h["name"].lower() == name.lower():
                return h["value"]
        return ""

    def _collect_threads(self, service, messages):
        seen_threads = set()
        threads = []
        for msg_ref in messages[:50]:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"],
                    format="metadata", metadataHeaders=["Subject", "From", "To"],
                ).execute()
            except Exception:
                continue
            thread_id = msg.get("threadId")
            if not thread_id or thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)
            headers = msg.get("payload", {}).get("headers", [])
            subject = self._get_header(headers, "Subject")
            to = self._get_header(headers, "To")
            name = extract_email_name(to)
            threads.append({"subject": subject, "to": name or to})
        return threads

    def _find_kept_label_id(self, service):
        """Find the 'kept' Gmail label ID."""
        result = service.users().labels().list(userId="me").execute()
        for label in result.get("labels", []):
            if label["name"] == "kept":
                return label["id"]
        return None

    def _fetch_kept_threads(self, service, label_id):
        """Fetch threads with the 'kept' label."""
        result = service.users().messages().list(
            userId="me", labelIds=[label_id], maxResults=20
        ).execute()
        messages = result.get("messages", [])
        seen_threads = set()
        threads = []
        for msg_ref in messages:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"],
                    format="metadata", metadataHeaders=["Subject", "From"],
                ).execute()
            except Exception:
                continue
            thread_id = msg.get("threadId")
            if not thread_id or thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)
            headers = msg.get("payload", {}).get("headers", [])
            subject = self._get_header(headers, "Subject")
            from_header = self._get_header(headers, "From")
            name = extract_email_name(from_header)
            threads.append({"subject": subject, "from": name or from_header, "thread_id": thread_id})
        return threads

    def _load_processed_kept_ids(self):
        state_file = config.get_kept_state_path()
        try:
            with open(state_file) as f:
                return set(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def _save_processed_kept_ids(self, ids):
        state_file = config.get_kept_state_path()
        with open(state_file, "w") as f:
            json.dump(sorted(ids), f)
