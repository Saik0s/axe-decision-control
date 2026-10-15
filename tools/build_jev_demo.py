"""Build a portable visual lesson from actual Jev 1.14 recordings and answers."""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

from axe_control.decisions import StrictModel
from axe_control.models import Event
from benchmarks.summarize import Episode, saved_proof_issues
from tools.record_jev_demos import JudgmentCapture

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results/jev-1.14-2026-10-15"
BOX_ATTEMPTS = (
    "box", "box-atomic-visibility/box", "box-crop-refinement/box", "box-described-targets/box",
    "box-image-fix/box",
)


class BoxStep(StrictModel):
    step: int
    image: str
    event: Event
    executed: bool
    requests: list[JudgmentCapture]


def url(path: Path) -> str:
    return "../" + path.relative_to(ROOT).as_posix()


def read_episode(path: Path) -> Episode:
    return Episode.model_validate_json((path / "episode.json").read_bytes())


def steps(path: Path, episode: Episode) -> list[BoxStep]:
    if episode.report is None:
        raise ValueError("Missing recorded report")
    grouped: dict[int, list[JudgmentCapture]] = {}
    step = 0
    for line in (path / "questions.jsonl").read_text().splitlines():
        capture = JudgmentCapture.model_validate_json(line)
        if "operation" in capture.questions:
            step += 1
        if "target" in capture.questions:
            grouped.setdefault(step, []).append(capture)
    return [BoxStep(
        step=event.step, image=url(path / f"step-{event.step:02}.png"), event=event,
        executed=any(item.step == event.step and item.phase == "act"
                     for item in episode.report.events),
        requests=grouped.get(event.step, []),
    ) for event in episode.report.events if event.phase == "decide" and event.box is not None]


def card(label: str, description: str, path: Path, episode: Episode) -> str:
    report = episode.report
    if report is None:
        raise ValueError("Missing recorded report")
    passed = not episode.issues() and not saved_proof_issues(episode, path)
    clip = path / "original.mp4"
    elapsed = report.elapsed_seconds
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(clip),
    ], text=True))
    cost = "Unknown cost" if report.reported_cost_usd is None else (
        f"${report.reported_cost_usd:.9f} reported cost")
    return f'''<article><div class="overline">{html.escape(label)}</div>
<h2>{html.escape(description)}</h2><span class="status {'pass' if passed else 'blocked'}">
{'Independent pass' if passed else 'Blocked / failed'}</span>
<video controls playsinline preload="metadata" poster="{url(path / 'final.png')}"
 aria-label="Jev 1.14 {label} native simulator recording" src="{url(clip)}"></video>
<p class="metrics">{report.decision_requests} requests · {elapsed:.3f} s controller<br>
{cost} · {duration:.2f} s clip</p><p class="caption">{html.escape(report.reason)}</p>
<a href="{url(path / 'episode.json')}">Independent evidence</a> ·
<a href="{url(path / 'questions.jsonl')}">Actual questions &amp; answers</a></article>'''


TEMPLATE = (Path(__file__).with_name("templates") / "jev-demo.html").read_text(
    encoding="utf-8",
).removesuffix("\n")


def main() -> None:
    selected = RUNS / BOX_ATTEMPTS[-1]
    episodes = [read_episode(RUNS / "tree"), read_episode(RUNS / "grid"), read_episode(selected)]
    if any(item.scenario != episodes[0].scenario or item.screen != episodes[0].screen
           or item.seed != episodes[0].seed for item in episodes):
        raise ValueError("Demos must use the same scenario, seed and geometry")
    cards = "\n".join(
        card(label, description, folder, episode)
        for label, description, folder, episode in zip(
            ("Tree", "Grid", "Box"),
            ("Choose an observed target", "Refine a screen region", "Return the control's edges"),
            (RUNS / "tree", RUNS / "grid", selected), episodes, strict=True,
        )
    )
    attempts = []
    for relative in BOX_ATTEMPTS:
        folder = RUNS / relative
        episode = read_episode(folder)
        report = episode.report
        if report is None:
            raise ValueError("Missing box attempt report")
        attempts.append(f'<p><a href="{url(folder / "episode.json")}">{html.escape(relative)}</a>'
                        f' · {report.status} · {report.decision_requests} requests · '
                        f'{html.escape(report.reason)} · <a href="{url(folder / "original.mp4")}">'
                        'Original recording</a></p>')
    payload = json.dumps([item.model_dump() for item in steps(selected, episodes[-1])])
    result = TEMPLATE.replace("__CARDS__", cards).replace(
        "__STEPS__", payload.replace("</", "<\\/"),
    )
    result = result.replace("__SCREEN__", episodes[-1].screen.model_dump_json())
    result = result.replace("__HERO_IMAGE__", url(selected / "step-05-box.png"))
    result = result.replace("__ATTEMPTS__", "\n".join(attempts))
    result = result.replace("__ATTEMPT_HEADING__", "Five attempts retained. The latest completes.")
    result = result.replace("__ATTEMPT_TEXT__", (
        "The first three attempts stopped below the presence or confidence gates. "
        "A caller-supplied workflow target catalog made the next control explicit, but "
        "that fourth run failed with HTTP 400 on a 278-by-394-pixel Quiet mode crop. "
        "The fifth run uses the same catalog, enlarged refinement crops and the adapter's "
        "empirical 280-pixel minimum side. It completed Review PR for 50 minutes with "
        "Quiet mode on and passed independent app and saved-proof checks. "
        "The presence and confidence gates remain 0.90 and 0.80."
    ))
    (ROOT / "docs/jev-1.14.html").write_text(result)
    print("Built docs/jev-1.14.html from three native demos and all retained box attempts")


if __name__ == "__main__":
    main()
