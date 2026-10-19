// Injected after each MiniWoB++ task's own scripts (see server.py).
(function () {
  var q = new URLSearchParams(location.search);
  var run = q.get('bench_run') || '';
  var seed = q.get('seed') || '0';
  var task = location.pathname.split('/').pop().replace(/\.html$/, '');

  // LLM agents are far slower than the 10 s default; BrowserGym also lifts this limit.
  core.EPISODE_MAX_TIME = 24 * 3600 * 1000;

  var reported = false;
  var origEnd = core.endEpisode;
  core.endEpisode = function (reward, timeProportional, reason) {
    var live = core.EP_TIMER !== null;
    origEnd.apply(this, arguments);
    if (!live || reported) return;
    reported = true;
    fetch('/__bench/result', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
      body: JSON.stringify({
        run: run, task: task, seed: seed,
        reward: WOB_REWARD_GLOBAL, raw_reward: WOB_RAW_REWARD_GLOBAL,
        reason: String(WOB_REWARD_REASON)
      })
    });
    // One episode per attempt: replace the START cover with a dead "finished" screen.
    if (core.cover_div) {
      core.cover_div.innerHTML = 'EPISODE FINISHED';
      core.cover_div.onclick = null;
    }
  };

  window.onload = function () {
    Math.seedrandom(task + ':' + seed);
    core.startEpisode();
    core.startEpisodeReal();
  };
})();
