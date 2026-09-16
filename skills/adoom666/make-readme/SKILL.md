---
name: make-readme
description: Generate or update a comprehensive README.md based on deep codebase analysis
---

# makeReadme Skill

Generate an exhaustive README.md by analyzing the entire codebase structure, functionality, and development history.

## Execution Steps

### 1. Explore Codebase Structure
- Run `find . -type f | head -100` and `tree -L 3` (or equivalent) to map the file structure
- Identify the project type: Lambda, API, web app, library, CLI tool, etc.
- Locate key files: entry points, configs, schemas, deployment scripts
- Check for existing README.md to determine update vs. create

### 2. Read Development History
- Check for `.prompt_history` file in the project root
- If exists, read it to extract:
  - Development decisions and rationale
  - Known issues encountered during development
  - Evolution of the project architecture
  - Technical debt notes

### 3. Mine Recent Learnings & Context
Gather institutional knowledge that should be captured in the README for future developers:

- **Memory files:** Check for `MEMORY.md` or any `.md` files in:
  - `.claude/projects/*/memory/` (Claude project memory)
  - `.claude/memory/` (global memory)
  - Extract: architectural decisions, known bugs/fixes, deployment gotchas, config quirks
- **CLAUDE.md files:** Check project root and `.claude/` dirs for `CLAUDE.md`
  - Extract: project-specific conventions, environment setup, workflow notes
- **Kanban/task history:** Check for kanban DB or TODO.md
  - Extract: recently completed work, fixes applied, features added
- **Troubleshooting files:** Check for `troubleshooting.md` in project root
  - Extract: resolved issues, root causes, workarounds
- **Git log (recent):** Run `git log --oneline -20` to capture recent changes
  - Extract: what's been actively worked on, deployment history

**What to include in README from this context:**
- Patches or workarounds currently in place (and why)
- Non-obvious configuration requirements discovered through debugging
- Infrastructure decisions and their rationale
- Known limitations with current approach
- Upgrade/migration notes (what breaks, what to watch for)

**What NOT to include:**
- Session-specific temporary state
- API keys, tokens, or credentials (even if found in memory)
- Personal preferences or communication style notes

### 4. Analyze Key Components
Adopt a SME now that you know everything in the code to do deep analysis.Depending on project type, investigate:

**For Lambdas/Serverless:**
- Handler files and entry points
- Event triggers (API Gateway, S3, SNS, etc.)
- Environment variables and secrets
- IAM permissions required
- Deployment scripts/configs (SAM, Serverless, CDK)

**For APIs:**
- Route definitions and endpoints
- Request/response schemas
- Authentication mechanisms
- Middleware stack

**For Web Apps:**
- Component structure
- State management
- Build configuration
- Routing

**For Libraries:**
- Public API surface
- Export structure
- Peer dependencies

### 5. Document the Following Sections

```markdown
# [Project Name]

> [One-line description]

## Overview
[2-3 paragraph explanation of what this does and why it exists]

## Architecture
```
[ASCII diagram showing data flow, components, integrations]
```

## File Structure
```
project/
├── src/              # [Description]
│   ├── handlers/     # [Description]
│   └── utils/        # [Description]
├── deploy.sh         # [Description]
└── requirements.txt  # [Description]
```

## Configuration

### Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `VAR_NAME` | Yes/No | What it does |

### AWS Resources (if applicable)
- Lambda ARN: `arn:aws:lambda:...`
- API Gateway: `https://...`
- DynamoDB Table: `table-name`

## Dependencies
[List key dependencies and their purposes]

## Local Development
```bash
# Setup steps
# How to run locally
# How to test
```

## Deployment
```bash
# Deployment commands
# Required permissions
# Post-deployment verification
```

## API Reference (if applicable)
### `POST /endpoint`
**Request:**
```json
{ "field": "value" }
```
**Response:**
```json
{ "result": "value" }
```

## Database Schema (if applicable)
| Field | Type | Description |
|-------|------|-------------|
| `pk` | String | Partition key |

## Testing
```bash
# How to run tests
# Example test commands
```

## Known Issues & Technical Debt
- [ ] Issue 1
- [ ] Issue 2

## Development History
[Context from .prompt_history about how this evolved]

## Recent Changes & Active Patches
[Document any patches, workarounds, or recent significant changes that future developers need to know about. Include rationale and conditions for removal.]

### Active Workarounds
| Workaround | Why | Remove When |
|------------|-----|-------------|
| [Description] | [Root cause] | [Condition for removal] |

## Troubleshooting
### Common Error: [Error Name]
**Cause:** [Why it happens]
**Solution:** [How to fix]
```

### 6. Update vs. Create Logic
- If README.md exists:
  - Read existing content
  - Preserve any manual additions (like contributor notes, badges)
  - Update sections that have become stale
  - Add new sections for undocumented features
- If README.md doesn't exist:
  - Create from scratch with full template

### 7. Formatting Standards
- Use ATX-style headers (`#`, `##`, `###`)
- Use fenced code blocks with language specifiers
- Use tables for structured data (env vars, schemas, API params)
- Include clickable table of contents for long READMEs
- Keep line length reasonable (no horizontal scroll)
- Use collapsible sections (`<details>`) for verbose content

### 8. Final Validation
- Verify all file paths mentioned actually exist
- Confirm environment variables match actual usage in code
- Ensure deployment instructions are accurate to deploy scripts
- Check that API endpoints match route definitions

## Output
Report back with:
- ✅ README.md [created/updated] at `[path]`
- Summary of major sections added
- Any gaps that couldn't be filled (missing info, unclear code)
