"""iMessage database utilities."""

import sqlite3
import os
import sys


def get_connection():
    """
    Get a read-only connection to the Messages database.
    Exits with helpful error if access is denied.
    """
    db_path = os.path.expanduser('~/Library/Messages/chat.db')

    if not os.path.exists(db_path):
        print(f"Error: Messages database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        conn.execute("SELECT 1 FROM message LIMIT 1")
        return conn
    except sqlite3.OperationalError as e:
        raise PermissionError(
            f"Unable to open Messages database: {e}\n"
            "Grant Full Disk Access:\n"
            "  System Settings > Privacy & Security > Full Disk Access > Add your terminal app"
        ) from e


def extract_text_from_attributed_body(blob):
    """
    Extract text from macOS attributedBody BLOB field.

    The attributedBody contains an NSAttributedString in a binary format.
    The actual text is stored after the "NSString" marker with a length prefix.
    """
    if not blob:
        return None

    try:
        parts = blob.split(b"NSString")
        if len(parts) < 2:
            return None

        text_data = parts[1][5:]  # Skip 5-byte preamble

        if text_data[0] == 129:  # Length encoded in 2 bytes
            length = int.from_bytes(text_data[1:3], "little")
            text_bytes = text_data[3:length + 3]
        else:  # Length in single byte
            length = text_data[0]
            text_bytes = text_data[1:length + 1]

        return text_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return None
