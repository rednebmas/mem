# Actions

Actions are optional post-processing plugins that piggyback on the single routing LLM call for free detection. Each action adds a detection prompt to the routing call and receives structured flags in the output — no extra LLM calls needed for the detection step.

This keeps mem's core focused on building topic hierarchies, while actions extend it with automation that benefits from the same data.

## How It Works

1. **Detection** — Each action contributes a prompt snippet that gets appended to the routing LLM call. The LLM sees the instructions alongside the normal topic routing and outputs structured flags for each action.
2. **Dispatch** — After routing, mem passes each action's flags to its handler.
3. **Handling** — The handler does whatever it wants: make its own LLM calls, hit APIs, send notifications. Handlers run after topic routing is complete.

## Built-in Actions

### auto-calendar

Detects scheduling conversations in text messages and creates/manages calendar events. Supports four event states:

- **create** — Confirmed plans become regular calendar events
- **hold** — Proposed-but-unconfirmed plans become `[HOLD]` prefixed events
- **confirm_hold** — Confirmation of a previous hold removes the `[HOLD]` prefix
- **delete** — Cancellations remove events

Holds auto-expire after 2 days or 1 hour before event start.

Enable in `config.json`:

```json
{
  "actions": ["auto-calendar"]
}
```

## Creating a Custom Action

An action needs two things: a detection prompt and a handler.

### 1. Detection Prompt

A markdown file with instructions for the routing LLM. This gets appended to the routing prompt, so the LLM sees it alongside the topic routing instructions.

Example — `~/my-actions/auto-reply/detect.md`:
```
UNANSWERED MESSAGES: If any text conversations show messages from others
that {user} hasn't responded to in 24+ hours, flag them in the "auto_reply"
field with the person's name and the unanswered message.
```

Note: `{user}` is replaced with the instance user's name automatically.

### 2. Output Schema

An `output.json` file next to your detect.md that defines the JSON fields your action adds to the routing output:

Example — `~/my-actions/auto-reply/output.json`:
```json
{
  "auto_reply": [
    {"person": "Contact Name", "message": "the unanswered message"}
  ]
}
```

### 3. Handler

An executable that receives the flagged JSON on stdin and takes action.

Example — `~/my-actions/auto-reply/handler.py`:
```python
#!/usr/bin/env python3
import json, sys

flags = json.loads(sys.stdin.read())
for item in flags.get("auto_reply", []):
    print(f"Draft reply for {item['person']}: {item['message'][:50]}...")
    # ... generate a response, send a notification, etc.
```

### 4. Config

Add the action to your instance's `config.json`:

```json
{
  "actions": [
    "auto-calendar",
    {
      "name": "auto-reply",
      "prompt": "~/my-actions/auto-reply/detect.md",
      "handler": "~/my-actions/auto-reply/handler.py"
    }
  ]
}
```

Built-in actions (like `auto-calendar`) are referenced by name string. External actions use an object with `name`, `prompt`, and `handler` fields.

## Notifications

Actions that want to notify the user can use the `notify_command` config:

```json
{
  "notify_command": "~/scripts/notify-telegram.sh"
}
```

The command receives the notification message on stdin. Any action handler can call it, and the built-in auto-calendar uses it for event creation/hold/confirmation/expiry notifications.
