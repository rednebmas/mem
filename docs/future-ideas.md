# Future Ideas

## Agent Types

The core architecture — topic hierarchies, decay scoring, LLM routing — is domain-agnostic. Rather than genericizing the current personal-life prompt (which would water it down), the right approach is separate agent types with their own prompts and rules tuned for the domain.

### Codebase Summarizer

A `mem` agent type that watches a codebase and maintains a living topic tree of what's evolving. A collector plugin runs `git log --patch` (or watches a CI pipeline), and the routing prompt is tuned for code: modules, features, architectural patterns instead of personal life categories.

The output `TOPICS.md` goes into the repo's system prompt, giving every new Claude Code session instant context about what's active — no manual onboarding needed.

**What it would need:**
- A codebase-specific routing prompt (different examples, rules, and noise filtering)
- A git-diff collector plugin
- Seed topics based on repo structure (modules, services, layers)
- Bio describes the codebase instead of a person

### Team Activity Tracker

Same idea applied to team communication — Slack channels, PR reviews, meeting notes. The topic tree organizes around projects, initiatives, and decisions rather than personal interests.

## Auto-Reply for Unanswered Messages

An action plugin that detects unanswered text messages and drafts suggested responses. The routing LLM already sees all text conversations — an action plugin could flag messages where someone is waiting for a reply and suggest a response via notification for the user to approve.

See also: `~/code/brain/tasks/auto-reply-unanswered-texts.md`
