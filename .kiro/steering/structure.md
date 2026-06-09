# Project Structure

> This project is in early setup. Update this file as the structure evolves.

## Current Layout

```
repos/
├── .git/                   # Git version control
├── .kiro/
│   ├── specs/              # Feature specs (requirements, design, tasks)
│   └── steering/           # AI assistant guidance files
└── README.md               # Project overview (currently empty)
```

## Conventions to Establish

As the project grows, follow these organizational guidelines:

- **Source code** should live in a `src/` directory
- **Tests** should mirror the source structure (e.g., `src/foo.ts` → `tests/foo.test.ts`)
- **Configuration files** (build, lint, env) belong at the project root
- **Secrets and environment variables** must never be committed; use `.env.example` to document required variables
- Keep feature-specific code co-located (components, styles, logic, tests together) rather than split by file type

## Spec Files

Feature specs are stored under `.kiro/specs/{feature-name}/`:
- `requirements.md` — user stories and acceptance criteria
- `design.md` — technical design and architecture
- `tasks.md` — implementation task list
