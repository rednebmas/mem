"""Shared Google OAuth authentication for email and calendar tools.

Credential paths are resolved from the mem instance directory if available,
falling back to ~/.config/mem/.
"""

import os
import sys

# These will be overridden by _resolve_paths() on first use
_credentials_file = None
_token_file = None

# Combined scopes for all Google tools
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
]


def _resolve_paths():
    """Resolve credential/token paths from config or defaults."""
    global _credentials_file, _token_file
    if _credentials_file is not None:
        return

    config_dir = os.path.expanduser('~/.config/mem')
    _credentials_file = os.path.join(config_dir, 'google_oauth.json')
    _token_file = os.path.join(config_dir, 'google_token.json')


def get_credentials():
    """Get authenticated Google credentials with all required scopes."""
    _resolve_paths()

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Error: Required packages not installed.", file=sys.stderr)
        print("Run: pip install google-auth-oauthlib google-api-python-client", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(_credentials_file):
        print(f"Error: OAuth credentials not found at {_credentials_file}", file=sys.stderr)
        print("\nSetup instructions:", file=sys.stderr)
        print("1. Go to https://console.cloud.google.com/", file=sys.stderr)
        print("2. Create/select a project", file=sys.stderr)
        print("3. Enable Gmail API and Google Calendar API", file=sys.stderr)
        print("4. Create OAuth 2.0 credentials (Desktop app)", file=sys.stderr)
        print(f"5. Download and save as {_credentials_file}", file=sys.stderr)
        sys.exit(1)

    creds = None
    if os.path.exists(_token_file):
        creds = Credentials.from_authorized_user_file(_token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(_credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        token_dir = os.path.dirname(_token_file)
        os.makedirs(token_dir, exist_ok=True)
        with open(_token_file, 'w') as token:
            token.write(creds.to_json())

    return creds


def get_gmail_service():
    """Get authenticated Gmail service."""
    from googleapiclient.discovery import build
    return build('gmail', 'v1', credentials=get_credentials())


def get_calendar_service():
    """Get authenticated Google Calendar service."""
    from googleapiclient.discovery import build
    return build('calendar', 'v3', credentials=get_credentials())
