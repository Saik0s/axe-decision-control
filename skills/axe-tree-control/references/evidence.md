# Recorded evidence and its limits

Historical snapshot: frozen corrected synthetic native comparison, 2026-10-05,
with **105 matched episodes** across all included routes. The repository's
`docs/results.md` and `results/native-comparison/summary.json` hold the fuller
record; this summary travels with the installed skill and needs no checkout.
The table below is the tree/grid subset, not all 105 episodes.

| Route | Strict passes | Independently reached outcomes |
| --- | --- | --- |
| Clef tree | 12/15 | 12/15 |
| JeV 1.13 tree | 12/15 | 15/15 |
| Winnow tree | 3/15 | 4/15 |
| Clef grid | 0/15 | 0/15 |
| Winnow grid | 0/15 | 2/15 |

Clef/Winnow grid had **0/30 strict passes in that frozen 2026-10-05 comparison**.
These are not current JeV 1.14 grid or box statistics. Missing accessibility
semantics alone is not a reason to launch an experimental visual route. An
explicit visual-control request is required, together with an image-ready
service and an authorized destination.

Separate capability evidence, 2026-10-15: parent source verification of the
[JeV 1.14 listing](https://openrouter.ai/typesafe/jev-1.14) and
[endpoint metadata](https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints)
identified text+image decisions and resolved `typesafe/jev-1.14-20261014`.
The parent reported a live `/alpha/decisions` request with `text` + `image_url`
state parts and Noul + Box questions returning HTTP 200 and an actual box.
This establishes wire support, not a successful simulator goal, fresh demo,
calibration, or measured JeV 1.14 control accuracy.

A strict pass combined controller completion, independently checked fixture
state, visible final facts, and valid proof/exit accounting. A model's fresh
`completed` judgment alone is weaker evidence. These small synthetic samples
do not establish reliability for another app, model revision, or service.
For the current goal, report independent facts, model belief, and anything still
unchecked separately. Never reuse benchmark outcomes as proof of a new run.
