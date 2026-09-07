# Issue tracker: Local Markdown

Issues and specs for this repository live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Work status is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history are appended under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/`, creating the directory when needed.

## When a skill says "fetch the relevant ticket"

Read the referenced file in full. The user will normally provide its path or issue number.

## Wayfinding operations

Used by `/wayfinder`. A map has one child file per ticket.

- **Map**: `.scratch/<effort>/map.md`
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`
- **Blocking**: a `Blocked by: NN, NN` line near the top
- **Frontier**: the first open, unblocked, and unclaimed ticket by number
- **Claim**: set `Status: claimed` before beginning work
- **Resolve**: append the result under `## Answer`, set `Status: resolved`, and update the map
