# Current first-three media audit

**Verdict: all three original recordings decode fully and support their saved report/oracle outcomes. `gpt-direct` and `clef-tree` succeeded; `clef-grid` remained blocked in the editor.**

Scope is exactly `benchmark-runs/annotation-final-105/{gpt-direct,clef-tree,clef-grid}/basic/repeat-0`, using the synthetic FocusBench fixture. Expected outcome: a running session named **Ship demo**, **25 minutes**, **Quiet on**. These are three individual episodes, not a matrix result or a success-rate estimate.

| Lane | Original video length / decoded frames | Actual final screenshot and last video frame | Report / oracle |
| --- | --- | --- | --- |
| gpt-direct | 15.871667 s / 148 | Session started; Ship demo; 25 minutes; Quiet mode on | completed, exit 0; running / Ship demo / 25 / true |
| clef-tree | 14.661667 s / 129 | Session started; Ship demo; 25 minutes; Quiet mode on | completed, exit 0; running / Ship demo / 25 / true |
| clef-grid | 13.245000 s / 43 | New session editor; empty name field with Session name placeholder; 25 min selected; Quiet Off; faded Start session button | blocked, exit 2; editing / empty / 25 / false |

Video lengths are media durations, not benchmark runtimes. Saved run-report status and selected counters agree with episode.json for all three lanes. All three have zero saved setup/proof failures; this does not turn grid's blocked episode into a success.

Beginning, temporal midpoint, and last decoded frames were inspected with image tools, alongside each **actual source final.png**, separately. Representative source PTS in seconds:

- gpt-direct: 0.000000 / 7.915000 / 15.868333. [Beginning](gpt-direct/frame-01.png), [middle](gpt-direct/frame-02.png), [end](gpt-direct/frame-03.png).
- clef-tree: 0.000000 / 7.318333 / 14.660000. [Beginning](clef-tree/frame-01.png), [middle](clef-tree/frame-02.png), [end](clef-tree/frame-03.png).
- clef-grid: 0.000000 / 6.641667 / 13.236667. [Beginning](clef-grid/frame-01.png), [middle](clef-grid/frame-02.png), [end](clef-grid/frame-03.png).

Direct/tree midpoint frames show **Ship demo inside the editor** even though Session started is not yet present. Missing a completion label does not mean typed text is missing. Grid's final editor actually contains no entered text, so its phase/name/Quiet failures are visually supported. Grid's saved screenshot places controls lower than its last video frame, but the observed phase, name, duration, and Quiet state agree.

Full ffmpeg decoding used `-copyts`, `-fps_mode passthrough`, and one decoder, encoder, and filter thread. All runs reached EOF with exit 0; decoded counts match ffprobe. Source PTS are unique and monotonic, with variable intervals retained as exact ticks at time base 1/600. No original media was modified or retimed.

Warning confirmation with `repeat+warning` produced only null-output non-monotonic DTS warnings: direct 102, tree 93, grid 10. No decoder error markers or other warnings were observed. These null-output timestamp warnings are **not evidence of corrupt frames**.

[Machine-readable evidence](evidence.json) records full SHA-256 hashes and byte sizes for each original.mp4, final.png, episode.json, run-report.json, and final-tree.json. All **15 source files** still matched after review. Per-lane technical.json files retain exact frame PTS, sampled-image hashes, decode results, and semantic observations. Source paths are repository-relative; derived paths are relative to this folder. Raw model/auth/error bodies and private host paths are excluded.

**Blockers:** none for this review. Visual inspection sampled representative frames rather than every interaction; no matrix-wide result, model-error cause, or source-to-build provenance is inferred.

**Next action:** use direct/tree as successful first-episode evidence and label grid as blocked. Review the later four current recordings separately after they exist.
