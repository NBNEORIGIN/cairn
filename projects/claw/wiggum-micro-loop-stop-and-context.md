# CLAW — WIGGUM Micro Loop: Stop Button + Context Assembly

Use this micro loop to harden CLAW against two high-value explanation prompts.

## Goal

Make CLAW reliably answer these prompts without validation failures, invented file paths, or long stalls:

1. `Read the CLAW codebase and explain how the stop button works end to end. Only use files inside the CLAW repo itself. Name the web UI file, the Next.js proxy route, the FastAPI endpoint, and where the agent cooperatively stops an in-flight request.`
2. `Explain how CLAW assembles context for a chat request, including core.md, hybrid retrieval, mentions, recent history, and manual skills.`

## Method

Run a tight assess → execute → validate loop.

### Assess

- Call the local evaluator against `projects/claw/eval_stop_and_context_suite.json`.
- Inspect:
  - validation failures
  - executed tools
  - hallucinated file names
  - empty-response/time-out paths

### Execute

- Apply the smallest fix that improves answer quality.
- Prefer:
  - safer repo-only search behavior
  - better validation retry prompts
  - better context assembly for explanation prompts
  - better file-grounding rules

Do not:

- add broad one-off hacks for exact prompt strings
- rewrite the request path
- add new dependencies

### Validate

Re-run the same two-prompt evaluator after each fix.

Success means both prompts pass with:

- all required markers present
- no forbidden markers
- no validation failure text returned to the user
- no blank answer

## Stop Condition

Exit immediately once both prompts pass in the evaluator.

## Deliverable

Report:

- iteration count
- files changed
- final evaluator result
- any remaining residual risks
