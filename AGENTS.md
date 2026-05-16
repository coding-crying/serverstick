# AGENTS.md — ServerStick Project

## Goal

ServerStick: USB plug-and-play self-hosting. The PLAN.md file is the single source of truth for what we've decided. Conversations explore options, validate ideas, and work through problems. **When something is confirmed, it goes into PLAN.md.**

## Working Rules

1. **PLAN.md is sacred.** Only add things we're sure about. If we haven't tested it or agreed on it, it stays in conversation, not in the plan.
2. **Mark uncertainty.** Every section in PLAN.md should note what's still untested. If something is "decided but unvalidated", say so.
3. **Rejected ideas go in PLAN.md too.** Under "Explicitly Rejected" — so we don't revisit the same debates.
4. **Validate before adding.** Don't write aspirational architecture into PLAN.md. Write what we've confirmed works or what we've firmly decided on.

## Project Location

`/home/will/ServerStick/`

## Current Status

P2 backlog. Concept/planning phase. No repo yet (other than local directory).

## Key Context

- This is a USB installer, not a persistent live OS. It writes Debian to the host disk.
- Pi (github.com/earendil-works/pi) is the LLM harness — used as a dependency, NOT forked.
- SOPS + age for secrets. No Vault, no server process.
- Two API keys: starter (baked, low value) and earnings (XMR mining, on-device, high value).
- Target users are non-technical. Zero-config is the philosophy.