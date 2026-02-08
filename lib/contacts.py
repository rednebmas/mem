"""macOS Contacts database utilities."""

import sqlite3
import os
import re
from pathlib import Path


def normalize_phone(phone):
    """Normalize phone number to just digits for comparison."""
    if not phone:
        return ''
    return re.sub(r'[^\d]', '', phone)


def get_contact_databases():
    """Find all AddressBook databases (main + sources)."""
    base_path = Path.home() / 'Library' / 'Application Support' / 'AddressBook'
    dbs = []

    main_db = base_path / 'AddressBook-v22.abcddb'
    if main_db.exists():
        dbs.append(main_db)

    sources_dir = base_path / 'Sources'
    if sources_dir.exists():
        for source_dir in sources_dir.iterdir():
            if source_dir.is_dir():
                source_db = source_dir / 'AddressBook-v22.abcddb'
                if source_db.exists():
                    dbs.append(source_db)

    return dbs


def load_contacts():
    """
    Load all contacts into a dict mapping phone numbers to names.
    Returns dict: normalized_phone -> display_name
    """
    phone_to_name = {}

    for db_path in get_contact_databases():
        try:
            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    p.ZFULLNUMBER,
                    COALESCE(r.ZNICKNAME, '') as nickname,
                    COALESCE(r.ZFIRSTNAME, '') as first,
                    COALESCE(r.ZLASTNAME, '') as last,
                    COALESCE(r.ZORGANIZATION, '') as org
                FROM ZABCDPHONENUMBER p
                JOIN ZABCDRECORD r ON p.ZOWNER = r.Z_PK
                WHERE p.ZFULLNUMBER IS NOT NULL
            """)

            for phone, nickname, first, last, org in cursor.fetchall():
                normalized = normalize_phone(phone)
                if not normalized:
                    continue

                if nickname:
                    name = nickname
                elif first or last:
                    name = f"{first} {last}".strip()
                elif org:
                    name = org
                else:
                    continue

                phone_to_name[normalized] = name
                if len(normalized) > 10:
                    phone_to_name[normalized[-10:]] = name

            conn.close()
        except Exception:
            continue

    return phone_to_name


class ContactResolver:
    """Resolves phone numbers/handles to contact names."""

    def __init__(self):
        self._phone_to_name = None

    @property
    def phone_map(self):
        if self._phone_to_name is None:
            self._phone_to_name = load_contacts()
        return self._phone_to_name

    def resolve(self, handle):
        """
        Resolve a handle (phone number or email) to a contact name.
        Returns the contact name if found, otherwise the original handle.
        """
        if not handle:
            return 'Unknown'

        normalized = normalize_phone(handle)
        if normalized in self.phone_map:
            return self.phone_map[normalized]

        if len(normalized) > 10:
            short = normalized[-10:]
            if short in self.phone_map:
                return self.phone_map[short]

        return handle
