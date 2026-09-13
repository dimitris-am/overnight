# Brief: tally

## Mission

Build `tally`, a small command-line tool in Python (standard library only) that counts lines, words, and characters in one or more files, like `wc`.

## Hard constraints

- Python 3.9+ standard library only; no third-party packages
- No network access

## Must-have

1. `tally FILE...` prints lines, words, and characters per file, plus a total row when more than one file is given
2. `--json` prints the same data as JSON
3. A missing file prints a clear error to stderr and exits non-zero

## Done-criteria

- `python3 -m unittest discover -s tests` passes
- `python3 tally.py README.md BRIEF.md` prints two rows and a total row
- `python3 tally.py --json README.md` prints valid JSON with lines, words, and characters
- README.md documents usage with examples

## Guardrails

- Work only inside this repository
- Commit after every passing milestone; never force-push
