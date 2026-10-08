# Preserved interrupted native run

This is an **incomplete baseline**, not the final comparison. It contains 100
valid attempted episodes out of 105 expected, with all 100 saved proof sets
validated. Forty-six passed the strict controller/outcome/proof checks. Five
expected Winnow-grid episodes are missing. No missing episode is counted as a
success or replaced with a result from another implementation.

The original matrix process ended with exit 2 while the host disk was full.
Its final ledger was not closed. Pending/null final fingerprints trigger the
coverage check's `implementation_or_runtime_changed` and unfinished issues;
this does not establish a code change during a completed cell. The six finished
cells had matching before/after fingerprints. The source was preserved before
the subsequent annotation repair.

The measured renderer had an audited defect: opaque fine-cell labels covered
red tap centers in the full screenshot and spilled beyond the refined region.
Its enlarged crop retained visible markers. The defect's effect on individual
model failures is unknown. Five completed Clef-grid attempts also received
HTTP 529; provider errors must not be presented as grounding errors.

The corrected implementation contains cell-sized labels and draws all center
markers after labels and grid lines. It is measured in a separate frozen
comparison, rather than mixed into this baseline.

`partial-summary.json` is recomputed from actual episode reports and saved
proof. `interruption.json` records the terminal process observation and coverage.
`expected-matrix.json` and `matrix-run.json` are unchanged original records.
`measured-source.tar.gz` contains all 29 fingerprinted source/config files from
this baseline. Original videos, screenshots and synthetic tree/oracle records
remain present, including failures.

Final evaluation labels such as `visible_name_missing` refer to required result
labels, not whether an editor contains an entered name. A field can hold the
right value while the session remains unstarted. Inspect phase, oracle values,
screenshots and controller status together.

This dataset contains synthetic FocusBench content only. It is not a production
reliability, calibrated confidence or causal performance study. The full matrix
report generator intentionally refuses its incomplete coverage.
