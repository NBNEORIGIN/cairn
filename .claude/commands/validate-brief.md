Validate a brief in `briefs/` against the actual repo state. Catches
mechanical errors — wrong file paths, fictional table names, missing
endpoints, unknown symbols — before a fresh session burns time on
them.

Run the validator and report the result:

```bash
python scripts/validate_brief.py $ARGUMENTS
```

If it exits 1, surface the unverified references and decide whether
each is:
- **a real error** — fix the brief before handing it off, or
- **design intent** — a new file/symbol/table the brief is asking the
  implementer to *create*, in which case it's expected to be missing
  pre-implementation.

The validator only catches mechanical errors. Design-shaped issues
(overlap with existing components, project-key ambiguity, scope creep
into spanning-brief territory) still need human review per Pattern B.
