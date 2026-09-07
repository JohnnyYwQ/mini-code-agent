# Domain Docs

How engineering skills should consume this repository's domain documentation.

## Before exploring, read these

- `CONTEXT.md` at the repository root, or `CONTEXT-MAP.md` if one exists
- Relevant ADRs under `docs/adr/`
- Context-specific ADRs when a multi-context repository defines them

If these files do not exist, proceed silently. `/domain-modeling` creates them lazily when terminology or durable decisions are resolved.

## File structure

This repository uses a single context:

```text
.
├── CONTEXT.md
├── docs/
│   └── adr/
└── src/
    ├── main/
    │   ├── python/
    │   └── resources/
    └── test/
        └── python/
```

## Use the glossary's vocabulary

When an output names a domain concept, use the term defined in `CONTEXT.md`. Do not drift to synonyms that the glossary explicitly avoids.

If a required concept is absent, reconsider whether it is genuine project language or note the gap for `/domain-modeling`.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding it.
