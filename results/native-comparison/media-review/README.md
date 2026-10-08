# Original recording review

These are the first `basic/repeat-0` recordings from all seven cells in the
complete corrected native comparison. They illustrate actual behavior, not
matrix success rates. All seven original videos fully decoded successfully:
**1188 frames**, with native timestamps and no retiming. Start, middle and end
frames were inspected against each saved final screenshot and episode state.

[Portable source manifest](summary.json) names the original files relative to
the native comparison dataset directory, with their SHA-256 hashes and sizes.
All **35 original video/still/episode/report/tree files** were rehashed after
copying. The two original audits below retain their original `benchmark-runs`
paths as provenance; use the portable manifest to locate the shared copies.

- [GPT direct, Clef tree and Clef grid](media-current-first3/audit.md).
- [Jev tree and the three Winnow modes](media-current-final4/audit.md).

GPT direct, Clef tree, Jev tree and Winnow direct completed this first task.
Clef grid stopped in the editor with an empty name and Quiet mode off.
Winnow tree and grid stopped in the editor with `Ship demo`, 25 minutes and
Quiet mode on, before starting the session. Missing completion-screen labels
do not mean those editor values were absent. All outcomes remain visible.

The recordings are variable-frame-rate. Winnow grid retains one repeated
presentation timestamp. FFmpeg's null-output non-monotonic DTS warnings were
distinguished from decode errors; no source frames or timestamps were rewritten.
