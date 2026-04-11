# Cairn backfill data directory

Hand-authored YAML inputs for the counterfactual memory backfill importer.

## Files

- `disputes.yml.template` — annotated template for Phase 3 disputes source
- `b2b_quotes.yml.template` — annotated template for Phase 6 b2b_quotes source

## How to start authoring

```bash
cp scripts/backfill/data/disputes.yml.template scripts/backfill/data/disputes.yml
cp scripts/backfill/data/b2b_quotes.yml.template scripts/backfill/data/b2b_quotes.yml
# Then edit the .yml files in place — they are gitignored so you
# can freely name real clients, real numbers, and real settlements.
```

## Privacy

`scripts/backfill/data/*.yml` is gitignored. The templates (`*.template`)
and this README are committable. Only the templates ship in the repo.

## Testing as you author

```bash
python -m scripts.backfill.run --source disputes --dry-run --sample-size 3
python -m scripts.backfill.run --source b2b_quotes --dry-run --sample-size 3
```

Dry-run writes nothing to the database. It parses the YAML, runs the
archetype tagger over each record, and prints the first N as a sample.
If the parser rejects a case it tells you exactly which `case_id` and
`phase` are wrong.

When everything looks right:

```bash
python -m scripts.backfill.run --source disputes --commit
python -m scripts.backfill.report <run_id>
```

The report prints archetype distribution, signal strength histogram,
and the rollback SQL if the run needs to be undone.
