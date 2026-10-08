# Current final-four media audit

**Verdict: all four recordings decode fully. Jev tree and Winnow direct complete the goal; Winnow tree and Winnow grid remain blocked in the editor.**

Scope: benchmark-runs/annotation-final-105/{jev-tree,winnow-direct,winnow-tree,winnow-grid}/basic/repeat-0, synthetic FocusBench. Expected: running **Ship demo**, **25 minutes**, **Quiet on**. Each decode waited for terminal episode.json with saved proof pointing to the exact original.mp4.

| Lane | Original video length / decoded frames | Actual final screenshot and last video frame | Report / oracle |
| --- | --- | --- | --- |
| jev-tree | 10.983333 s / 111 | Session started, Ship demo, 25 minutes, Quiet mode on. | completed, exit 0; running / Ship demo / 25 / true |
| winnow-direct | 23.905000 s / 145 | Session started, Ship demo, 25 minutes, Quiet mode on. | completed, exit 0; running / Ship demo / 25 / true |
| winnow-tree | 11.985000 s / 135 | New session editor; Ship demo is present; 25 min selected; Quiet On; Start session button still visible. | blocked, exit 2; editing / Ship demo / 25 / true |
| winnow-grid | 88.548333 s / 477 | New session editor; Ship demo is present; 25 min selected; Quiet On; Start session button still visible. | blocked, exit 2; editing / Ship demo / 25 / true |

Lengths are media durations, not benchmark runtimes. Saved run-report status and selected counters agree with episode.json. Blocked outcomes remain blocked.

Image tools separately inspected beginning, temporal midpoint, last decoded frame, and each **actual source final.png**. Sample source PTS:

- jev-tree: 0.000000 / 5.486667 / 10.966667 seconds. [beginning](jev-tree/frame-01.png), [middle](jev-tree/frame-02.png), [end](jev-tree/frame-03.png).
- winnow-direct: 0.000000 / 13.983333 / 23.903333 seconds. [beginning](winnow-direct/frame-01.png), [middle](winnow-direct/frame-02.png), [end](winnow-direct/frame-03.png).
- winnow-tree: 0.000000 / 6.113333 / 11.970000 seconds. [beginning](winnow-tree/frame-01.png), [middle](winnow-tree/frame-02.png), [end](winnow-tree/frame-03.png).
- winnow-grid: 0.000000 / 48.733333 / 88.546667 seconds. [beginning](winnow-grid/frame-01.png), [middle](winnow-grid/frame-02.png), [end](winnow-grid/frame-03.png).

**Winnow tree and Winnow grid finish in the editor, although Ship demo is present, 25 min is selected, and Quiet is On in both final editors.** Evaluation reports visible_name_missing and visible_quiet_missing, but the editor visibly contains the name and Quiet On; the completion screen is absent. Jev midpoint also contains the name before completion; Winnow direct midpoint is an empty editor followed by a successful final screen. All intermediate observations are retained in [evidence.json](evidence.json).

Complete ffmpeg decoding used copyts, fps_mode passthrough and one decoder, encoder and filter thread. All **868 frames** reached EOF with exit 0 and matching ffprobe counts. Source PTS are nondecreasing. Winnow grid has one adjacent repeated source PTS at frames 18/19 (zero-based); other lanes have none. Variable intervals and the duplicate are retained as exact ticks. No original media were modified or retimed.

With repeat+warning, only null-output non-monotonic DTS warnings appeared: jev-tree 76; winnow-direct 106; winnow-tree 90; winnow-grid 335. No decoder error markers or other warnings were recorded. These timestamp warnings are **not corrupt-frame evidence**.

[Machine-readable evidence](evidence.json) and per-lane technical.json retain SHA-256 hashes and byte sizes for original.mp4, final.png, episode.json, run-report.json and final-tree.json. All **20 source files** matched after review. Exact source PTS, sampled-image hashes, decode counts and semantic observations are retained. Paths are relative; raw model/auth/error bodies and private host paths are excluded.

**Coverage: 4/4 this pass; 7/7 with the parent-accepted [first-three audit](../media-current-first3/audit.md).** That artifact was untouched and not re-reviewed. The seven recordings total **1188 decoded frames** and **35 source files**, including the parent-verified prior batch. This is not a full matrix result or lane success rate.

**Blockers:** none for this review. Visual checks sampled representative frames and actual final screenshots, not every interaction.

**Next action:** parent validates the final-four evidence against current source hashes, then uses both batches as current7 media evidence with blocked outcomes labeled accurately.
