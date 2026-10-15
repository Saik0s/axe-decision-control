/* Real recorded events; no simulator actions or model requests happen here. */
'use strict';
(() => {
  const select = document.querySelector('#recording');
  const video = document.querySelector('#recording-video');
  const previous = document.querySelector('#event-prev');
  const next = document.querySelector('#event-next');
  const trace = document.querySelector('#event-trace');
  let lesson = recordedLessons[0];
  let cursor = 0;
  const descriptions = {
    observe: 'Read a new observation. Direct and tree modes use accessibility; grid uses a screenshot.',
    decide: 'Ask the selected model to choose the next action. The controller validates the returned function or typed answer.',
    freshness: 'Read again before using the planned action. A stale observation prevents the old choice from being applied.',
    act: 'Execute the validated action through AXe. This is where the simulator can change.',
    verify: 'Compare the resulting observation with the previous one. A DONE action also requires a fresh completion check.',
  };
  const titles = {
    observe: 'Read the current screen', decide: 'Choose one permitted action',
    freshness: 'Recheck observation freshness', act: 'Execute through AXe', verify: 'Check the resulting state',
  };
  const put = (selector, value) => { document.querySelector(selector).textContent = value; };
  function renderEvent() {
    const event = lesson.events[cursor];
    put('#event-position', `Event ${cursor + 1} / ${lesson.events.length} · step ${event.step} · controller +${event.at_seconds.toFixed(3)} s`);
    put('#event-title', titles[event.phase] || event.phase);
    put('#event-description', descriptions[event.phase] || 'Saved controller telemetry. See the raw episode for the complete record.');
    const facts = [];
    if (event.operation) facts.push(`operation: ${event.operation}`);
    if (event.inside_belief !== null) facts.push(`inside belief: ${event.inside_belief.toFixed(4)} (uncalibrated)`);
    if (event.completion_belief !== null) facts.push(`completion belief: ${event.completion_belief.toFixed(4)} (uncalibrated)`);
    if (event.state_changed !== null) facts.push(`state changed: ${event.state_changed ? 'yes' : 'no'}`);
    put('#event-facts', facts.join(' · ') || 'No action recorded at this phase.');
    document.querySelectorAll('[data-phase]').forEach(element => {
      element.classList.toggle('active', element.dataset.phase === event.phase);
    });
    trace.querySelectorAll('div').forEach((element, index) => {
      element.classList.toggle('selected', index === cursor);
    });
    previous.disabled = cursor === 0;
    next.disabled = cursor === lesson.events.length - 1;
  }
  function chooseLesson() {
    lesson = recordedLessons.find(item => item.cell === select.value);
    cursor = 0;
    video.pause();
    video.src = lesson.video;
    video.poster = lesson.poster;
    video.load();
    video.setAttribute('aria-label', `${lesson.title}, recorded native simulator run`);
    put('#run-title', lesson.title);
    put('#run-model', `${lesson.model} · ${lesson.mode}`);
    const status = document.querySelector('#run-status');
    status.textContent = lesson.strict_pass ? 'Strict pass' : 'Strict failure';
    status.classList.toggle('fail', !lesson.strict_pass);
    put('#run-outcome', `${lesson.outcome_reached ? 'Native outcome reached.' : 'Native outcome not reached.'} Controller: ${lesson.reason}`);
    put('#run-timing', `Original clip ${lesson.video_seconds.toFixed(2)} s · controller wall time ${lesson.elapsed_seconds.toFixed(2)} s. Separate clocks, not a synchronized replay.`);
    document.querySelector('#episode-link').href = lesson.evidence;
    document.querySelector('#final-link').href = lesson.poster;
    trace.replaceChildren(...lesson.events.map(event => {
      const row = document.createElement('div');
      row.textContent = `+${event.at_seconds.toFixed(3)} s  step ${event.step}  ${event.phase}${event.operation ? ' / ' + event.operation : ''}`;
      return row;
    }));
    renderEvent();
  }
  previous.addEventListener('click', () => { if (cursor > 0) { cursor--; renderEvent(); } });
  next.addEventListener('click', () => { if (cursor < lesson.events.length - 1) { cursor++; renderEvent(); } });
  select.addEventListener('change', chooseLesson);
  const grid = document.querySelector('#grid-cells');
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 4; col++) {
      const button = document.createElement('button');
      const label = `${String.fromCharCode(65 + col)}${row + 1}`;
      button.type = 'button';
      button.textContent = label;
      button.setAttribute('aria-label', `Explore grid cell ${label}, column ${col + 1}, row ${row + 1}`);
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => {
        grid.querySelectorAll('button').forEach(item => {
          item.classList.remove('chosen'); item.setAttribute('aria-pressed', 'false');
        });
        button.classList.add('chosen'); button.setAttribute('aria-pressed', 'true');
        const pixelX = (col + .5) * 1206 / 4;
        const pixelY = (row + .5) * 2622 / 8;
        put('#grid-choice', `${label} center: (${pixelX.toFixed(2)}, ${pixelY.toFixed(2)}) pixels → (${(pixelX / 3).toFixed(2)}, ${(pixelY / 3).toFixed(2)}) logical points. The real planner refines this region into 16 fine cells before deciding whether to tap.`);
      });
      grid.append(button);
    }
  }
  chooseLesson();
})();
