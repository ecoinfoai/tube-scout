// Progress polling (T063).
//
// Reads job_id from data-job-id on the .progress-card root, polls
// /jobs/{id}/progress every 3 seconds, updates DOM, redirects to
// /jobs/{id}/results on completion.
"use strict";

(function () {
  const card = document.querySelector(".progress-card");
  if (!card) return;
  const jobId = card.dataset.jobId;
  if (!jobId) return;

  const stageLabel = document.getElementById("stage-label");
  const fill = document.getElementById("progress-fill");
  const processed = document.getElementById("processed-count");
  const total = document.getElementById("total-count");
  const statusMsg = document.getElementById("status-message");

  const POLL_MS = 3000;
  let stopped = false;

  async function tick() {
    if (stopped) return;
    try {
      const resp = await fetch(`/jobs/${encodeURIComponent(jobId)}/progress`, {
        credentials: "same-origin",
      });
      if (!resp.ok) {
        if (resp.status === 404) {
          stopped = true;
          if (statusMsg) {
            statusMsg.hidden = false;
            statusMsg.textContent = "작업을 찾을 수 없습니다.";
          }
          return;
        }
        throw new Error(`HTTP ${resp.status}`);
      }
      const payload = await resp.json();
      if (stageLabel && payload.stage_label_kr) {
        stageLabel.textContent = payload.stage_label_kr;
      }
      if (processed) processed.textContent = payload.processed ?? 0;
      if (total) total.textContent = payload.total ?? 0;
      if (fill) {
        const t = payload.total || 0;
        const p = payload.processed || 0;
        const pct = t > 0 ? Math.min(100, Math.round((p / t) * 100)) : 0;
        fill.style.width = `${pct}%`;
      }
      if (payload.status === "completed") {
        stopped = true;
        window.location.assign(`/jobs/${encodeURIComponent(jobId)}/results`);
        return;
      }
      if (payload.status === "failed" || payload.status === "interrupted") {
        stopped = true;
        if (statusMsg) {
          statusMsg.hidden = false;
          statusMsg.textContent =
            payload.error_message_kr || "분석이 중단되었습니다.";
          statusMsg.classList.remove("alert-info");
          statusMsg.classList.add("alert-error");
        }
        return;
      }
    } catch (err) {
      // intentional-skip: transient network/parse failures are retried on
      // the next tick. We do not surface to the operator here — a
      // permanent failure shows up via the job state machine within ~3s.
    }
    setTimeout(tick, POLL_MS);
  }

  setTimeout(tick, 200);
})();
