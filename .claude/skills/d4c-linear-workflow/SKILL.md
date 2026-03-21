---
name: d4c-linear-workflow
description: Delta 4C development workflow that connects Linear issues to git commits. Use this skill whenever working on Delta 4C code, creating commits, branching, or executing tasks from Linear issues. Also triggers when the user says "pick up an issue", "work on VAL-XX", "what's next", "commit this", "push this", or any reference to the Linear→Git→Code→Linear workflow. Always use this skill in combination with the d4c-brand skill when the task involves visual/UI work.
---

# D4C Linear → Git → Code → Linear Workflow

This skill enforces a disciplined dev workflow where every line of code traces back to a Linear issue, every commit references the issue ID, and every issue gets updated when work is done.

## The Loop

```
┌─────────────────────────────────────────────────────┐
│  1. PICK    → Find next issue from Linear           │
│  2. BRANCH  → Create branch (use Linear's name)     │
│  3. READ    → Read full issue description            │
│  4. CODE    → Execute the work (use d4c-brand)       │
│  5. COMMIT  → Atomic commits with Refs: VAL-XX       │
│  6. UPDATE  → Move issue state in Linear             │
│  7. PUSH    → Push branch, create PR                 │
│  8. NEXT    → Go back to step 1                      │
└─────────────────────────────────────────────────────┘
```

## Step 1: PICK — Find the next issue

Priority order:
1. Issues with state "In Progress" assigned to me
2. Issues with state "Backlog", sorted by priority (Urgent > High > Medium)
3. Respect `blockedBy` — don't pick blocked issues
4. Within epic VAL-9, follow: VAL-10 → VAL-11 → VAL-12 → VAL-16 → VAL-14 → VAL-13 → VAL-15

```bash
# Check what's in progress
linear issues --assignee me --state "In Progress"

# If nothing, check backlog
linear issues --assignee me --state "Backlog" --priority 1  # Urgent
linear issues --assignee me --state "Backlog" --priority 2  # High
```

When picking, announce: `"Picking up VAL-XX: {title}"`

## Step 2: BRANCH — Use Linear's gitBranchName

Every Linear issue has a pre-generated `gitBranchName`. ALWAYS use it:

```bash
git checkout main
git pull origin main
git checkout -b <gitBranchName>
```

**NEVER** invent branch names. The Linear branch names ensure automatic linking.

## Step 3: READ — Parse the issue fully

Before writing code, extract from the issue description:
- **What** to build (functional spec)
- **What exists** already (don't rebuild)
- **What's missing** (the actual work)
- **Design spec** (how it looks — defer to d4c-brand skill)
- **Definition of Done** (acceptance criteria)
- **Related issues** (context)

## Step 4: CODE — Execute with D4C brand

For ANY visual/UI work, load the d4c-brand skill first:
```
Read: .claude/skills/d4c-brand/SKILL.md
Read: .claude/skills/d4c-brand/references/components.md
```

Key rules:
- Use the `T` token object for all colors, fonts, spacing
- Reuse existing components from `frontend/src/components/d4c/`
- Follow the anti-patterns list (no emojis, no white backgrounds, no off-palette colors)
- Mobile responsive always
- BrandFooter on every client-facing output

For backend work:
- Follow existing patterns in `backend/agents/`
- Type hints everywhere (Pydantic models)
- Docstrings in Spanish (informal, same tone as Linear issues)

## Step 5: COMMIT — The format is sacred

```
<tipo>(<scope>): <descripción en español o inglés, corta>

<body opcional — qué y por qué, no cómo>

Refs: VAL-XX
```

### Commit types
| Type | When |
|------|------|
| `feat` | New functionality |
| `fix` | Bug fix |
| `style` | Visual changes only, no logic |
| `refactor` | Code restructure, same behavior |
| `docs` | Documentation |
| `chore` | Config, deps, tooling |
| `test` | Adding or fixing tests |

### Scopes
| Scope | Maps to |
|-------|---------|
| `design-system` | VAL-10 |
| `ko-report` | VAL-11, VAL-3 |
| `demo` | VAL-12, VAL-8 |
| `vaire` | VAL-16 |
| `onboarding` | VAL-14, VAL-6 |
| `portal` | VAL-13 |
| `operator` | VAL-15 |
| `swarm` | VAL-1, VAL-5 |
| `api` | Backend endpoints |
| `infra` | Docker, deploy, monitoring |
| `abstraction` | VAL-2 (business abstraction layer) |

### `Refs: VAL-XX` is MANDATORY

This is what connects git to Linear. Without it, the work is invisible.

For commits that touch multiple issues:
```
Refs: VAL-11, VAL-10
```

### Decomposition — atomic commits

One commit = one logical change. Decompose:

**BAD:**
```
feat(ko-report): complete KO Report v2 redesign
Refs: VAL-11
```

**GOOD:**
```
style(ko-report): migrate colors to D4C design tokens
Refs: VAL-11

feat(ko-report): add NavHeader with severity summary
Refs: VAL-11

feat(ko-report): redesign executive summary with hero numbers
Refs: VAL-11

feat(ko-report): add expandable FindingCards
Refs: VAL-11

style(ko-report): implement D4C chart theme for recharts
Refs: VAL-11

feat(ko-report): add print/PDF mode
Refs: VAL-11

feat(ko-report): add mobile responsive breakpoints
Refs: VAL-11
```

## Step 6: UPDATE — Move the issue in Linear

When a commit meaningfully progresses an issue:
```bash
# First commit on an issue → move to In Progress
linear issue VAL-XX --state "In Progress"

# All DoD criteria met → move to Done
linear issue VAL-XX --state "Done"
```

If you discover new work during execution:
```bash
# Create a child issue or related issue
linear issue create \
  --team Valinor \
  --title "Bug: chart tooltip not rendering on mobile" \
  --priority high \
  --label product \
  --project "Valinor Core — Swarm E2E" \
  --parent VAL-9
```

## Step 7: PUSH — Branch and PR

```bash
git push origin <branch-name>
```

PR convention:
- **Title:** `VAL-XX: <issue title>`
- **Body:** Link to Linear issue + bulleted list of changes
- **Labels:** same as Linear labels (product, infra, gtm)

## File Structure Convention

```
frontend/
├── src/
│   ├── app/
│   │   ├── demo/page.tsx           # VAL-12
│   │   ├── onboarding/page.tsx     # VAL-14
│   │   └── portal/
│   │       ├── page.tsx            # VAL-13
│   │       └── [reportId]/page.tsx # VAL-13
│   ├── components/
│   │   ├── d4c/                    # VAL-10 — shared design system
│   │   │   ├── tokens.ts
│   │   │   ├── HeroNumber.tsx
│   │   │   ├── FindingCard.tsx
│   │   │   ├── StatusBadge.tsx
│   │   │   ├── SectionHeader.tsx
│   │   │   ├── DataTable.tsx
│   │   │   ├── ScoreBar.tsx
│   │   │   ├── NavHeader.tsx
│   │   │   ├── BrandFooter.tsx
│   │   │   └── index.ts
│   │   ├── ko-report/              # VAL-11
│   │   │   ├── KOReportV2.tsx
│   │   │   ├── ExecutiveSummary.tsx
│   │   │   ├── FindingsSection.tsx
│   │   │   └── DataVisualization.tsx
│   │   ├── demo/                   # VAL-12
│   │   │   ├── SwarmAnimation.tsx
│   │   │   ├── DiscoveryFlow.tsx
│   │   │   └── DemoCTA.tsx
│   │   ├── onboarding/             # VAL-14
│   │   └── operator/               # VAL-15
│   └── lib/
│       └── design-tokens.ts        # VAL-10
backend/
├── agents/
│   ├── vaire/                      # VAL-16
│   │   ├── agent.py
│   │   ├── pdf_renderer.py
│   │   └── templates/
```

## Quick Command Reference

```bash
# Start working on next issue
pick-issue

# Branch for an issue
git checkout -b $(linear issue VAL-XX --field gitBranchName)

# Commit with proper format
git commit -m "feat(scope): description

Details here.

Refs: VAL-XX"

# Update issue state
linear issue VAL-XX --state "In Progress"
linear issue VAL-XX --state "Done"

# Create new issue discovered during work
linear issue create --team Valinor --title "..." --parent VAL-9

# Push and prep for PR
git push origin HEAD
```
