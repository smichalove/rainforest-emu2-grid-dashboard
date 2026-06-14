# Token Guard Rules

## Measure Twice, Cut Once (Planning Mode)

This workspace strictly enforces token-optimized operations to prevent runaway context burning. 

### Rules:
1. **Enforce Blueprinting**: The agent MUST explicitly generate a `.md` plan of action in a scratchpad or artifact directory before making any cross-file code modifications.
2. **Interrupt Before Execution**: The agent MUST pause execution and explicitly await human approval after blueprint generation. Do NOT attempt to auto-execute wide-scale edits without first verifying intent.
3. **Outsource Heavy Research**: Use specialized/localized context lookups (e.g. grep) or explicitly ask the user for specific documentation snippets rather than indexing massive, irrelevant dependency trees.

*Purpose*: Reviewing an architecture document costs pennies in context tokens; letting an agent blindly rewrite files back-and-forth because it misunderstood an API boundary will drain the token pool.
