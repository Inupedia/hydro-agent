/**
 * Hydro-Agent Archify workbench driver.
 * Click「用户/任务」to input; live progress panel shows the current step.
 */
(function () {
  const ACTION_NODE = {
    A01_CHECK_DATA: "task",
    A03_VALIDATE_SCHEME: "task",
    A05_FORECAST: "forecast",
    A06_DIAGNOSE: "task",
    A07_OPTIMIZE: "optimize",
    A08_GATE: "gate",
    A09_RESOLVE: "keep",
    A10_FREEZE: "freeze",
    A11_REPLAY: "replay",
    A12_EVALUATE_REPORT: "results",
  };

  const ACTION_TITLE = {
    A01_CHECK_DATA: "资料检查",
    A03_VALIDATE_SCHEME: "校验方案",
    A05_FORECAST: "基础预报（XAJ）",
    A06_DIAGNOSE: "预报诊断",
    A07_OPTIMIZE: "有限参数优化（XAJ）",
    A08_GATE: "Gate 把关",
    A09_RESOLVE: "落实 Gate 结论",
    A10_FREEZE: "冻结方案",
    A11_REPLAY: "历史回放（XAJ）",
    A12_EVALUATE_REPORT: "评估与报告",
  };

  const STEP_ORDER = [
    "A01_CHECK_DATA",
    "A03_VALIDATE_SCHEME",
    "A05_FORECAST",
    "A06_DIAGNOSE",
    "A07_OPTIMIZE",
    "A08_GATE",
    "A09_RESOLVE",
    "A10_FREEZE",
    "A11_REPLAY",
    "A12_EVALUATE_REPORT",
  ];

  const GATE_ZH = {
    KEEP: "维持原方案",
    ACCEPT: "接受候选方案",
    ROLLBACK: "回退原方案",
  };

  let taskId = null;
  let polling = null;
  let started = false;
  let seenActions = [];

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(text) {
    const el = $("hydro-status");
    if (el) el.textContent = text;
  }

  function setProgress({ title, detail, busy, steps, llmText, llmStreaming, phase }) {
    const titleEl = $("hydro-progress-title");
    const detailEl = $("hydro-progress-detail");
    const listEl = $("hydro-progress-steps");
    const panel = $("hydro-progress");
    const llmEl = $("hydro-llm");
    const llmWrap = $("hydro-llm-wrap");
    const chipEl = $("hydro-progress-phase");
    const barEl = $("hydro-progress-bar");
    if (panel) panel.dataset.busy = busy ? "1" : "0";
    if (titleEl) titleEl.textContent = title || "待命";
    if (detailEl) detailEl.textContent = detail || "";
    if (chipEl) {
      const label = phase || (busy ? "运行中" : "待命");
      chipEl.textContent = label;
      chipEl.dataset.tone = busy ? "live" : label === "已完成" ? "done" : "idle";
    }
    if (listEl && Array.isArray(steps)) {
      const total = steps.length || 1;
      const doneCount = steps.filter((s) => s.state === "done").length;
      const currentBoost = steps.some((s) => s.state === "current") ? 0.5 : 0;
      const fraction = Math.min(1, (doneCount + currentBoost) / total);
      if (barEl) barEl.style.width = `${Math.round(fraction * 100)}%`;
      listEl.innerHTML = steps
        .map(
          (s) => `
          <li data-state="${escapeHtml(s.state)}">
            <span class="hydro-dot" aria-hidden="true"></span>
            <span class="hydro-step-text">${escapeHtml(s.text)}</span>
            <span class="hydro-step-state">${
              s.state === "done" ? "完成" : s.state === "current" ? "进行中" : "待办"
            }</span>
          </li>`,
        )
        .join("");
    }
    if (llmWrap) {
      const show = Boolean(llmText) || Boolean(llmStreaming);
      llmWrap.hidden = !show;
      if (llmEl && show) {
        llmEl.textContent = llmText || "";
        llmEl.scrollTop = llmEl.scrollHeight;
      }
      llmWrap.dataset.streaming = llmStreaming ? "1" : "0";
    }
  }

  function fmtMetric(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(3);
  }

  function closeResultsPanel() {
    const panel = $("hydro-results");
    if (panel) panel.hidden = true;
  }

  async function showFinalResults(id) {
    const panel = $("hydro-results");
    if (!panel) return;
    panel.hidden = false;
    const body = $("hydro-results-body");
    const logEl = $("hydro-agent-log");
    if (body) body.innerHTML = "<p>正在加载最终结果…</p>";
    if (logEl) logEl.innerHTML = "<p>正在加载智能体日志…</p>";
    try {
      const [results, agentLog] = await Promise.all([
        api(`/api/tasks/${id}/results`),
        api(`/api/tasks/${id}/agent-log`),
      ]);
      const scheme = results.scheme || {};
      const gate = results.gate || null;
      const metrics = results.metrics || {};
      const forecasts = results.forecasts || [];
      const reports = results.report_artifacts || [];
      const leadBits = forecasts
        .slice(0, 3)
        .map((f) => {
          const leads = f.lead_values || {};
          return `L1=${fmtMetric(leads["1"] ?? leads[1])} / L2=${fmtMetric(leads["2"] ?? leads[2])} / L3=${fmtMetric(leads["3"] ?? leads[3])}`;
        })
        .join("<br/>");
      const gateStatus = gate ? gate.status : null;
      const gateLabel = gate ? GATE_ZH[gate.status] || gate.status : "无 Gate 记录";
      if (body) {
        body.innerHTML = `
          <p class="story">${escapeHtml(results.story_zh || "流程已完成。")}</p>
          <div class="hydro-metric-grid" role="group" aria-label="评估指标">
            <div class="hydro-metric"><span>NSE</span><strong>${fmtMetric(metrics.NSE)}</strong></div>
            <div class="hydro-metric"><span>KGE</span><strong>${fmtMetric(metrics.KGE)}</strong></div>
            <div class="hydro-metric"><span>MAE</span><strong>${fmtMetric(metrics.MAE)}</strong></div>
            <div class="hydro-metric"><span>Bias</span><strong>${fmtMetric(metrics.Bias)}</strong></div>
          </div>
          <div class="hydro-gate-banner" data-gate="${escapeHtml(gateStatus || "none")}">
            <span class="hydro-gate-label">Gate</span>
            <strong>${escapeHtml(gateLabel)}</strong>
          </div>
          <dl class="hydro-kv">
            <div><dt>任务</dt><dd>${escapeHtml(results.task_id)}</dd></div>
            <div><dt>阶段</dt><dd>${escapeHtml(results.phase_zh || results.phase)}</dd></div>
            <div><dt>方案</dt><dd><code>${escapeHtml(scheme.scheme_id || "—")}</code><em>${escapeHtml(scheme.status || "—")}</em></dd></div>
            <div><dt>预报摘要</dt><dd>${leadBits || "无"}</dd></div>
            <div><dt>产物</dt><dd class="hydro-links">${
              reports.length
                ? reports
                    .map(
                      (name) =>
                        `<a href="/api/tasks/${encodeURIComponent(id)}/report/${encodeURIComponent(name)}" target="_blank" rel="noreferrer">${escapeHtml(name)}</a>`,
                    )
                    .join("")
                : "无"
            }<a href="/api/tasks/${encodeURIComponent(id)}/report/agent-log.jsonl" target="_blank" rel="noreferrer">agent-log.jsonl</a></dd></div>
          </dl>
        `;
      }
      const rounds = agentLog.rounds || [];
      if (logEl) {
        if (!rounds.length) {
          logEl.innerHTML = '<p class="hydro-empty">暂无智能体轮次日志。</p>';
        } else {
          logEl.innerHTML = rounds
            .map((round) => {
              const obs = (round.tool_observations || []).map(escapeHtml).join("；") || "—";
              const metricsText = Object.entries(round.tool_metrics || {})
                .map(([k, v]) => `${escapeHtml(k)}=${fmtMetric(v)}`)
                .join("，");
              const status = round.tool_status_zh || round.tool_status || "待执行";
              const tone =
                String(round.tool_status || "").includes("ACCEPT") || status.includes("接受")
                  ? "ok"
                  : String(round.tool_status || "").includes("ROLLBACK") || status.includes("回退")
                    ? "warn"
                    : String(round.tool_status || "").includes("fail") || round.error
                      ? "bad"
                      : "neutral";
              return `
                <article class="round" data-tone="${tone}">
                  <header>
                    <div>
                      <span class="hydro-round-index">第 ${escapeHtml(String(round.round_number))} 轮</span>
                      <strong>${escapeHtml(round.action_zh || round.action || "决策")}</strong>
                    </div>
                    <span class="hydro-status-pill" data-tone="${tone}">${escapeHtml(status)}</span>
                  </header>
                  <p class="hydro-judgment"><span>业务判断</span>${escapeHtml(round.judgment_zh || round.rationale_summary || "—")}</p>
                  <p><span class="hydro-label">输入摘要</span>${escapeHtml(round.input_summary_zh || "—")}</p>
                  <p><span class="hydro-label">假设</span>${escapeHtml(round.hypothesis_zh || round.hypothesis || "—")}
                     <span class="hydro-label">理由</span>${escapeHtml(round.rationale_summary || "—")}</p>
                  <details>
                    <summary>模型原始输出</summary>
                    <pre>${escapeHtml(round.llm_output || "（无）")}</pre>
                  </details>
                  <details>
                    <summary>本轮 WorldState 输入 JSON</summary>
                    <pre>${escapeHtml(JSON.stringify(round.input_world_state || {}, null, 2))}</pre>
                  </details>
                  <p><span class="hydro-label">工具观测</span>${obs}</p>
                  <p><span class="hydro-label">工具指标</span>${metricsText || "—"}</p>
                  ${round.error ? `<p class="err"><span class="hydro-label">错误</span>${escapeHtml(round.error)}</p>` : ""}
                </article>
              `;
            })
            .join("");
        }
      }
    } catch (err) {
      console.error(err);
      if (body) body.innerHTML = `<p class="err">加载结果失败：${escapeHtml(String(err.message || err))}</p>`;
      if (logEl) logEl.innerHTML = "";
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function highlight(nodeId) {
    document.querySelectorAll("[data-node-id].hydro-active").forEach((n) => {
      n.classList.remove("hydro-active");
    });
    if (!nodeId) return;
    document.querySelectorAll(`[data-node-id="${nodeId}"]`).forEach((n) => {
      n.classList.add("hydro-active");
    });
  }

  function markDone(nodeId) {
    if (!nodeId) return;
    document.querySelectorAll(`[data-node-id="${nodeId}"]`).forEach((n) => {
      n.classList.add("hydro-done");
    });
  }

  function resetMarks() {
    document.querySelectorAll("[data-node-id].hydro-active, [data-node-id].hydro-done").forEach((n) => {
      n.classList.remove("hydro-active", "hydro-done");
    });
    seenActions = [];
  }

  async function api(path, init) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(init && init.headers) },
      ...init,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`API ${response.status}: ${detail || path}`);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function readForm() {
    return {
      basin_id: $("hydro-basin").value.trim(),
      model_id: "xaj",
      start_date: $("hydro-start-date").value,
      end_date: $("hydro-end").value,
      forcing_mode: $("hydro-forcing").value,
      base_scheme_id: "scheme-base",
      allow_optimization: $("hydro-optimize").checked,
      max_agent_decision_rounds: 20,
      max_optimization_cycles: 4,
    };
  }

  function openInputPanel() {
    const panel = $("hydro-panel");
    if (!panel) return;
    panel.hidden = false;
    highlight("user");
    setStatus("在第一步填写参数，然后点开始");
    $("hydro-basin")?.focus();
  }

  function closeInputPanel() {
    const panel = $("hydro-panel");
    if (panel) panel.hidden = true;
  }

  function setRunning(isRunning) {
    started = isRunning;
    const btn = $("hydro-run");
    if (btn) btn.disabled = isRunning;
    ["hydro-basin", "hydro-start-date", "hydro-end", "hydro-forcing", "hydro-optimize"].forEach(
      (id) => {
        const el = $(id);
        if (el) el.disabled = isRunning;
      },
    );
  }

  function buildStepList(timeline, currentAction, busy) {
    const done = new Set(
      timeline.map((item) => item.action).filter((a) => a && ACTION_TITLE[a]),
    );
    return STEP_ORDER.map((code) => {
      const name = ACTION_TITLE[code];
      if (code === currentAction && busy) {
        return { state: "current", text: name };
      }
      if (done.has(code)) {
        const item = [...timeline].reverse().find((t) => t.action === code);
        const label = item?.label || name;
        return { state: "done", text: label };
      }
      return { state: "todo", text: name };
    });
  }

  function renderLive(run, timeline) {
    const last = timeline.length ? timeline[timeline.length - 1] : null;
    const lastAction = last?.action || run.last_action || null;
    const busy = Boolean(run.worker_active) || run.status === "running";
    const llmStreaming = Boolean(run.llm_streaming);
    const llmText = run.llm_text || "";
    const llmError = run.llm_error || null;

    if (lastAction && !seenActions.includes(lastAction)) {
      seenActions.push(lastAction);
    }

    const node = ACTION_NODE[lastAction] || (busy ? "task" : null);
    if (node) {
      highlight(node);
      if (!busy || (last && last.action === lastAction)) markDone(node);
    }

    let title;
    let detail;
    if (run.status === "completed" || (run.phase === "E" && !run.needs_follow_up && !busy)) {
      title = "已完成";
      detail = `任务 ${run.task_id} · 阶段 ${run.phase}`;
    } else if (llmError) {
      title = "LLM / 执行出错";
      detail = llmError;
    } else if (llmStreaming) {
      title = "大模型正在输出";
      detail = run.llm_decision_action
        ? `本轮将决策为 ${ACTION_TITLE[run.llm_decision_action] || run.llm_decision_action}`
        : "下方实时显示模型流式文本（含思考过程）";
      highlight("task");
    } else if (!lastAction && busy) {
      title = "智能体决策中";
      detail = "正在连接 SiliconFlow…";
      highlight("task");
    } else if (busy && lastAction) {
      const name = ACTION_TITLE[lastAction] || lastAction;
      title = `当前：${name}`;
      detail = last?.label
        ? `${last.label} · 若停住，可能在跑 XAJ 或等下一轮大模型`
        : "工具执行中，或等待下一轮大模型";
    } else if (lastAction) {
      title = `停在：${ACTION_TITLE[lastAction] || lastAction}`;
      detail = last?.label || `状态 ${run.status} · 阶段 ${run.phase}`;
    } else {
      title = "准备中";
      detail = `状态 ${run.status} · 阶段 ${run.phase}`;
    }

    setProgress({
      title,
      detail,
      busy: busy || llmStreaming,
      phase: run.phase ? `阶段 ${run.phase}` : busy ? "运行中" : "待命",
      steps: buildStepList(timeline, lastAction, busy || llmStreaming),
      llmText: llmText || (llmStreaming ? "（等待首个 token…）" : ""),
      llmStreaming,
    });
    setStatus(`${title} · ${detail}`);
  }

  async function startRun() {
    if (started) return;
    const payload = readForm();
    if (!payload.basin_id || !payload.start_date || !payload.end_date) {
      setStatus("请先填写流域和日期");
      return;
    }
    if (payload.end_date < payload.start_date) {
      setStatus("结束日期不能早于开始日期");
      return;
    }

    setRunning(true);
    closeInputPanel();
    closeResultsPanel();
    resetMarks();
    highlight("task");
    setProgress({
      title: "正在创建任务",
      detail: "提交参数到 API…",
      busy: true,
      steps: buildStepList([], null, true),
    });

    try {
      const task = await api("/api/tasks", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      taskId = task.task_id;
      markDone("user");
      markDone("task");
      setProgress({
        title: "已创建，正在启动",
        detail: taskId,
        busy: true,
        steps: buildStepList([], null, true),
      });
      await api(`/api/tasks/${taskId}/run`, { method: "POST" });
      setProgress({
        title: "智能体决策中",
        detail: "SiliconFlow 选择第一步；真实 XAJ 会比演示慢很多",
        busy: true,
        steps: buildStepList([], null, true),
      });
      startPolling();
    } catch (err) {
      console.error(err);
      setStatus(String(err.message || err));
      setProgress({
        title: "启动失败",
        detail: String(err.message || err),
        busy: false,
        steps: [],
      });
      setRunning(false);
      openInputPanel();
    }
  }

  function startPolling() {
    if (polling) clearInterval(polling);
    const tick = async () => {
      if (!taskId) return;
      try {
        const [run, timeline] = await Promise.all([
          api(`/api/tasks/${taskId}/run`),
          api(`/api/tasks/${taskId}/timeline`),
        ]);
        renderLive(run, timeline);
        if (run.status === "completed" || (run.phase === "E" && !run.needs_follow_up && !run.worker_active)) {
          highlight("results");
          markDone("results");
          clearInterval(polling);
          polling = null;
          setRunning(false);
          setProgress({
            title: "已完成 · 请看右侧最终结果",
            detail: `任务 ${taskId}`,
            busy: false,
            phase: "已完成",
            steps: buildStepList(timeline, "A12_EVALUATE_REPORT", false),
            llmText: run.llm_text || "",
            llmStreaming: false,
          });
          void showFinalResults(taskId);
        }
      } catch (err) {
        console.error(err);
        setStatus(String(err.message || err));
        setProgress({
          title: "轮询出错",
          detail: String(err.message || err),
          busy: false,
          steps: [],
        });
        setRunning(false);
      }
    };
    void tick();
    polling = setInterval(tick, 350);
  }

  function mountUi() {
    if ($("hydro-panel")) return;

    const style = document.createElement("style");
    style.textContent = `
      @import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Sora:wght@500;600;700&display=swap");

      :root {
        --hydro-ink: #0b1f2a;
        --hydro-muted: #4a6573;
        --hydro-line: rgba(11, 31, 42, 0.12);
        --hydro-surface: rgba(247, 251, 253, 0.92);
        --hydro-surface-solid: #f7fbfd;
        --hydro-accent: #0d7a6f;
        --hydro-accent-soft: rgba(13, 122, 111, 0.12);
        --hydro-deep: #083f3a;
        --hydro-warn: #9a6700;
        --hydro-danger: #b42318;
        --hydro-ok: #0f766e;
        --hydro-shadow: 0 18px 40px rgba(8, 35, 48, 0.14);
        --hydro-radius: 18px;
        --hydro-font: "IBM Plex Sans", "PingFang SC", "Segoe UI", sans-serif;
        --hydro-display: "Sora", "IBM Plex Sans", "PingFang SC", sans-serif;
        --hydro-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      }

      [data-node-id="user"],
      [data-node-id="task"] { cursor: pointer !important; }
      [data-node-id].hydro-active {
        filter: drop-shadow(0 0 0.55rem rgba(13, 122, 111, 0.9));
        outline: 3px solid var(--hydro-accent);
        outline-offset: 4px;
      }
      [data-node-id].hydro-done { opacity: 0.92; }

      #hydro-progress,
      #hydro-results,
      #hydro-panel {
        font-family: var(--hydro-font);
        color: var(--hydro-ink);
        -webkit-font-smoothing: antialiased;
      }

      #hydro-progress,
      #hydro-results {
        position: fixed;
        z-index: 2147483646;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        max-height: calc(100vh - 24px);
        padding: 0;
        border-radius: var(--hydro-radius);
        background:
          linear-gradient(165deg, rgba(255,255,255,0.72), transparent 42%),
          linear-gradient(180deg, #e8f4f2 0%, var(--hydro-surface-solid) 38%, #f4f8fa 100%);
        border: 1px solid var(--hydro-line);
        box-shadow: var(--hydro-shadow);
        backdrop-filter: blur(14px);
        overflow: hidden;
      }

      #hydro-progress {
        top: 12px;
        left: 12px;
        width: min(360px, calc(100vw - 24px));
      }
      #hydro-progress[data-busy="1"] {
        border-color: color-mix(in srgb, var(--hydro-accent) 45%, var(--hydro-line));
        box-shadow: 0 0 0 3px var(--hydro-accent-soft), var(--hydro-shadow);
      }

      #hydro-results {
        top: 12px;
        right: 12px;
        width: min(460px, calc(100vw - 24px));
      }
      #hydro-results[hidden] { display: none !important; }

      .hydro-side-head {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        padding: 0.95rem 1rem 0.35rem;
      }
      .hydro-side-mark {
        width: 0.55rem;
        height: 2.4rem;
        border-radius: 999px;
        background: linear-gradient(180deg, #1aa6a0, var(--hydro-deep));
        flex: 0 0 auto;
        margin-top: 0.15rem;
      }
      .hydro-side-head > div { flex: 1; min-width: 0; }
      .hydro-side-head .eyebrow {
        margin: 0 0 0.2rem;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--hydro-muted);
        font-weight: 600;
      }
      #hydro-progress-title,
      #hydro-results .hydro-side-title {
        margin: 0;
        font-family: var(--hydro-display);
        font-size: 1.12rem;
        font-weight: 600;
        line-height: 1.3;
        letter-spacing: -0.02em;
      }
      #hydro-progress[data-busy="1"] #hydro-progress-title::after {
        content: "";
        display: inline-block;
        width: 0.5rem;
        height: 0.5rem;
        margin-left: 0.45rem;
        border-radius: 999px;
        background: var(--hydro-accent);
        vertical-align: middle;
        animation: hydro-pulse 1.1s ease-in-out infinite;
      }
      @keyframes hydro-pulse {
        0%, 100% { opacity: 0.35; transform: scale(0.85); }
        50% { opacity: 1; transform: scale(1); }
      }

      .hydro-chip {
        flex: 0 0 auto;
        min-height: 28px;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        border: 1px solid var(--hydro-line);
        background: rgba(255,255,255,0.7);
        color: var(--hydro-muted);
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        display: inline-flex;
        align-items: center;
      }
      .hydro-chip[data-tone="live"] {
        color: var(--hydro-deep);
        border-color: color-mix(in srgb, var(--hydro-accent) 40%, transparent);
        background: var(--hydro-accent-soft);
      }
      .hydro-chip[data-tone="done"] {
        color: var(--hydro-ok);
        border-color: color-mix(in srgb, var(--hydro-ok) 35%, transparent);
        background: rgba(15, 118, 110, 0.1);
      }

      .hydro-track {
        margin: 0 1rem;
        height: 4px;
        border-radius: 999px;
        background: rgba(11, 31, 42, 0.08);
        overflow: hidden;
      }
      #hydro-progress-bar {
        display: block;
        height: 100%;
        width: 0%;
        border-radius: inherit;
        background: linear-gradient(90deg, #149e96, var(--hydro-deep));
        transition: width 220ms ease-out;
      }

      #hydro-progress-detail {
        margin: 0;
        padding: 0 1rem;
        color: var(--hydro-muted);
        font-size: 0.8rem;
        line-height: 1.5;
      }

      #hydro-progress-steps {
        list-style: none;
        margin: 0;
        padding: 0.15rem 0.7rem 0.85rem;
        display: grid;
        gap: 0.2rem;
        overflow: auto;
        max-height: min(44vh, 420px);
        scrollbar-width: thin;
      }
      #hydro-progress-steps li {
        display: grid;
        grid-template-columns: 1rem 1fr auto;
        align-items: center;
        gap: 0.55rem;
        min-height: 2.15rem;
        padding: 0.35rem 0.55rem;
        border-radius: 10px;
        font-size: 0.78rem;
        color: var(--hydro-muted);
        position: relative;
        transition: background 180ms ease, color 180ms ease;
      }
      #hydro-progress-steps li::before {
        content: "";
        position: absolute;
        left: calc(0.55rem + 0.35rem);
        top: -0.2rem;
        bottom: -0.2rem;
        width: 1px;
        background: rgba(11, 31, 42, 0.08);
      }
      #hydro-progress-steps li:first-child::before { top: 50%; }
      #hydro-progress-steps li:last-child::before { bottom: 50%; }
      .hydro-dot {
        width: 0.7rem;
        height: 0.7rem;
        border-radius: 999px;
        border: 2px solid rgba(11, 31, 42, 0.18);
        background: #fff;
        z-index: 1;
        justify-self: center;
      }
      .hydro-step-text { min-width: 0; line-height: 1.35; }
      .hydro-step-state {
        font-size: 0.68rem;
        color: rgba(74, 101, 115, 0.85);
        letter-spacing: 0.02em;
      }
      #hydro-progress-steps li[data-state="done"] {
        color: color-mix(in srgb, var(--hydro-ink) 78%, transparent);
      }
      #hydro-progress-steps li[data-state="done"] .hydro-dot {
        border-color: var(--hydro-accent);
        background: var(--hydro-accent);
        box-shadow: inset 0 0 0 2px #fff;
      }
      #hydro-progress-steps li[data-state="done"] .hydro-step-state { color: var(--hydro-ok); }
      #hydro-progress-steps li[data-state="current"] {
        background: var(--hydro-accent-soft);
        color: var(--hydro-deep);
        font-weight: 600;
      }
      #hydro-progress-steps li[data-state="current"] .hydro-dot {
        border-color: var(--hydro-accent);
        background: #fff;
        box-shadow: 0 0 0 3px rgba(13, 122, 111, 0.18);
        animation: hydro-pulse 1.1s ease-in-out infinite;
      }
      #hydro-progress-steps li[data-state="current"] .hydro-step-state { color: var(--hydro-accent); }
      #hydro-progress-steps li[data-state="todo"] { opacity: 0.72; }

      #hydro-llm-wrap {
        margin: 0 0.85rem 0.95rem;
        padding-top: 0.15rem;
        border-top: 1px solid var(--hydro-line);
      }
      #hydro-llm-wrap[hidden] { display: none !important; }
      #hydro-llm-wrap .eyebrow {
        margin: 0.55rem 0 0.35rem;
        font-size: 0.7rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--hydro-muted);
        font-weight: 600;
      }
      #hydro-llm-wrap[data-streaming="1"] .eyebrow::after {
        content: " · 接收中";
        color: var(--hydro-accent);
      }
      #hydro-llm {
        margin: 0;
        max-height: 26vh;
        overflow: auto;
        padding: 0.65rem 0.7rem;
        border-radius: 12px;
        background: linear-gradient(180deg, #0c1c22, #10262c);
        color: #d7efe8;
        font: 0.72rem/1.5 var(--hydro-mono);
        white-space: pre-wrap;
        word-break: break-word;
        border: 1px solid rgba(255,255,255,0.06);
      }

      #hydro-results-scroll {
        overflow: auto;
        padding: 0 1rem 1.1rem;
        display: grid;
        gap: 0.75rem;
        scrollbar-width: thin;
      }
      #hydro-results .story {
        margin: 0;
        padding: 0.7rem 0.8rem;
        border-radius: 12px;
        background: rgba(255,255,255,0.72);
        border: 1px solid var(--hydro-line);
        color: color-mix(in srgb, var(--hydro-ink) 88%, transparent);
        font-size: 0.86rem;
        line-height: 1.55;
      }
      .hydro-metric-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.5rem;
      }
      .hydro-metric {
        padding: 0.7rem 0.75rem;
        border-radius: 12px;
        background: rgba(255,255,255,0.78);
        border: 1px solid var(--hydro-line);
        display: grid;
        gap: 0.2rem;
      }
      .hydro-metric span {
        font-size: 0.7rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--hydro-muted);
        font-weight: 600;
      }
      .hydro-metric strong {
        font-family: var(--hydro-display);
        font-size: 1.2rem;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.03em;
        color: var(--hydro-deep);
      }
      .hydro-gate-banner {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        min-height: 2.6rem;
        padding: 0.55rem 0.8rem;
        border-radius: 12px;
        border: 1px solid var(--hydro-line);
        background: rgba(255,255,255,0.75);
      }
      .hydro-gate-label {
        font-size: 0.68rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--hydro-muted);
        font-weight: 700;
      }
      .hydro-gate-banner strong { font-size: 0.92rem; }
      .hydro-gate-banner[data-gate="ACCEPT"] {
        background: rgba(15, 118, 110, 0.1);
        border-color: rgba(15, 118, 110, 0.28);
        color: var(--hydro-ok);
      }
      .hydro-gate-banner[data-gate="KEEP"] {
        background: rgba(11, 31, 42, 0.04);
      }
      .hydro-gate-banner[data-gate="ROLLBACK"] {
        background: rgba(154, 103, 0, 0.1);
        border-color: rgba(154, 103, 0, 0.28);
        color: var(--hydro-warn);
      }
      .hydro-kv {
        margin: 0;
        display: grid;
        gap: 0.4rem;
      }
      .hydro-kv > div {
        display: grid;
        grid-template-columns: 4.6rem 1fr;
        gap: 0.45rem;
        padding: 0.45rem 0.55rem;
        border-radius: 10px;
        background: rgba(255,255,255,0.55);
        border: 1px solid rgba(11, 31, 42, 0.06);
      }
      .hydro-kv dt {
        color: var(--hydro-muted);
        font-size: 0.74rem;
        font-weight: 600;
      }
      .hydro-kv dd {
        margin: 0;
        font-size: 0.8rem;
        word-break: break-word;
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem 0.5rem;
        align-items: baseline;
      }
      .hydro-kv code {
        font-family: var(--hydro-mono);
        font-size: 0.72rem;
        background: rgba(11, 31, 42, 0.05);
        padding: 0.1rem 0.35rem;
        border-radius: 6px;
      }
      .hydro-kv em {
        font-style: normal;
        color: var(--hydro-muted);
        font-size: 0.72rem;
      }
      .hydro-links {
        display: flex !important;
        flex-wrap: wrap;
        gap: 0.35rem;
      }
      .hydro-links a,
      #hydro-results a {
        color: var(--hydro-accent);
        text-decoration: none;
        border-bottom: 1px solid color-mix(in srgb, var(--hydro-accent) 35%, transparent);
        font-weight: 500;
      }
      .hydro-links a:hover,
      #hydro-results a:hover { border-bottom-color: var(--hydro-accent); }
      .hydro-links a:focus-visible,
      #hydro-results a:focus-visible,
      #hydro-results-close:focus-visible,
      #hydro-run:focus-visible,
      #hydro-cancel:focus-visible {
        outline: 3px solid color-mix(in srgb, var(--hydro-accent) 45%, white);
        outline-offset: 2px;
      }

      .section-title {
        margin: 0.25rem 0 0;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        color: var(--hydro-muted);
        text-transform: uppercase;
        font-weight: 700;
      }
      #hydro-agent-log {
        display: grid;
        gap: 0.6rem;
      }
      #hydro-agent-log .round {
        padding: 0.7rem 0.75rem;
        border-radius: 14px;
        background: rgba(255,255,255,0.78);
        border: 1px solid var(--hydro-line);
        display: grid;
        gap: 0.35rem;
      }
      #hydro-agent-log .round[data-tone="ok"] {
        border-color: rgba(15, 118, 110, 0.28);
        box-shadow: inset 3px 0 0 var(--hydro-ok);
      }
      #hydro-agent-log .round[data-tone="warn"] {
        border-color: rgba(154, 103, 0, 0.28);
        box-shadow: inset 3px 0 0 var(--hydro-warn);
      }
      #hydro-agent-log .round[data-tone="bad"] {
        border-color: rgba(180, 35, 24, 0.28);
        box-shadow: inset 3px 0 0 var(--hydro-danger);
      }
      #hydro-agent-log .round header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 0.55rem;
        margin: 0;
      }
      #hydro-agent-log .round header strong {
        display: block;
        font-size: 0.88rem;
        letter-spacing: -0.01em;
      }
      .hydro-round-index {
        display: block;
        font-size: 0.68rem;
        color: var(--hydro-muted);
        letter-spacing: 0.04em;
        margin-bottom: 0.1rem;
        font-weight: 600;
      }
      .hydro-status-pill {
        flex: 0 0 auto;
        min-height: 1.55rem;
        padding: 0.15rem 0.5rem;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 700;
        border: 1px solid var(--hydro-line);
        background: rgba(11, 31, 42, 0.04);
        color: var(--hydro-muted);
        display: inline-flex;
        align-items: center;
      }
      .hydro-status-pill[data-tone="ok"] {
        color: var(--hydro-ok);
        background: rgba(15, 118, 110, 0.1);
        border-color: rgba(15, 118, 110, 0.25);
      }
      .hydro-status-pill[data-tone="warn"] {
        color: var(--hydro-warn);
        background: rgba(154, 103, 0, 0.1);
        border-color: rgba(154, 103, 0, 0.25);
      }
      .hydro-status-pill[data-tone="bad"] {
        color: var(--hydro-danger);
        background: rgba(180, 35, 24, 0.08);
        border-color: rgba(180, 35, 24, 0.25);
      }
      .hydro-judgment {
        margin: 0;
        padding: 0.5rem 0.6rem;
        border-radius: 10px;
        background: rgba(13, 122, 111, 0.07);
        font-size: 0.8rem;
        line-height: 1.45;
      }
      .hydro-judgment span,
      .hydro-label {
        display: inline-block;
        margin-right: 0.35rem;
        color: var(--hydro-muted);
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.04em;
      }
      #hydro-agent-log .round p {
        margin: 0;
        font-size: 0.78rem;
        line-height: 1.45;
        color: color-mix(in srgb, var(--hydro-ink) 88%, transparent);
      }
      #hydro-agent-log details {
        margin: 0.15rem 0;
        border-radius: 10px;
        background: rgba(11, 31, 42, 0.03);
        padding: 0.15rem 0.45rem;
      }
      #hydro-agent-log summary {
        cursor: pointer;
        font-size: 0.74rem;
        color: var(--hydro-muted);
        font-weight: 600;
        min-height: 1.8rem;
        display: flex;
        align-items: center;
      }
      #hydro-agent-log pre {
        margin: 0.25rem 0 0.45rem;
        max-height: 180px;
        overflow: auto;
        padding: 0.55rem 0.6rem;
        border-radius: 10px;
        background: linear-gradient(180deg, #0c1c22, #10262c);
        color: #d7efe8;
        font: 0.7rem/1.45 var(--hydro-mono);
        white-space: pre-wrap;
        word-break: break-word;
      }
      #hydro-agent-log .err,
      #hydro-results .err { color: var(--hydro-danger); }
      .hydro-empty {
        margin: 0;
        color: var(--hydro-muted);
        font-size: 0.8rem;
      }

      #hydro-results-close {
        min-width: 44px;
        min-height: 44px;
        margin: 0.35rem 0.35rem 0 0;
        border: 1px solid var(--hydro-line);
        border-radius: 12px;
        background: rgba(255,255,255,0.75);
        cursor: pointer;
        color: var(--hydro-muted);
        font: 0.78rem/1 var(--hydro-font);
        font-weight: 600;
        transition: background 160ms ease, color 160ms ease;
      }
      #hydro-results-close:hover {
        background: #fff;
        color: var(--hydro-ink);
      }

      #hydro-panel {
        position: fixed;
        z-index: 2147483647;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        width: min(420px, calc(100vw - 24px));
        padding: 1.05rem 1.15rem 1.15rem;
        border-radius: var(--hydro-radius);
        background:
          linear-gradient(165deg, rgba(255,255,255,0.85), transparent 40%),
          var(--hydro-surface-solid);
        border: 1px solid var(--hydro-line);
        box-shadow: var(--hydro-shadow);
      }
      #hydro-panel[hidden] { display: none !important; }
      #hydro-panel h2 {
        margin: 0 0 0.35rem;
        font-family: var(--hydro-display);
        font-size: 1.12rem;
        letter-spacing: -0.02em;
      }
      #hydro-panel .hint {
        margin: 0 0 0.9rem;
        color: var(--hydro-muted);
        font-size: 0.8rem;
        line-height: 1.5;
      }
      #hydro-panel .grid { display: grid; gap: 0.7rem; }
      #hydro-panel label {
        display: grid;
        gap: 0.3rem;
        font-size: 0.76rem;
        color: var(--hydro-muted);
        font-weight: 600;
      }
      #hydro-panel input,
      #hydro-panel select,
      #hydro-panel button {
        font: inherit;
        min-height: 44px;
        padding: 0.55rem 0.7rem;
        border-radius: 10px;
        border: 1px solid var(--hydro-line);
        background: #fff;
        color: var(--hydro-ink);
      }
      #hydro-panel .check {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        min-height: 44px;
      }
      #hydro-panel .check input { width: 1.1rem; height: 1.1rem; padding: 0; min-height: 0; }
      #hydro-panel .actions {
        display: flex;
        gap: 0.55rem;
        margin-top: 0.95rem;
      }
      #hydro-run {
        background: linear-gradient(180deg, #129388, var(--hydro-deep)) !important;
        color: #fff !important;
        border: 0 !important;
        cursor: pointer;
        font-weight: 700;
        flex: 1;
        transition: transform 160ms ease, filter 160ms ease;
      }
      #hydro-run:hover:not(:disabled) { filter: brightness(1.05); }
      #hydro-run:active:not(:disabled) { transform: scale(0.98); }
      #hydro-run:disabled { opacity: 0.55; cursor: not-allowed; }
      #hydro-cancel { background: transparent !important; cursor: pointer; }
      #hydro-status {
        margin: 0.8rem 0 0;
        font-size: 0.78rem;
        color: var(--hydro-muted);
        line-height: 1.45;
      }

      html[data-present="true"] .guided-views { display: none !important; }

      @media (max-width: 980px) {
        #hydro-results {
          left: 8px;
          right: 8px;
          top: auto;
          bottom: 8px;
          width: auto;
          max-height: 46vh;
        }
      }
      @media (max-width: 720px) {
        #hydro-progress {
          left: 8px;
          right: 8px;
          width: auto;
          max-height: 40vh;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        #hydro-progress-bar,
        #hydro-progress-steps li,
        #hydro-run,
        #hydro-results-close { transition: none !important; }
        #hydro-progress[data-busy="1"] #hydro-progress-title::after,
        #hydro-progress-steps li[data-state="current"] .hydro-dot {
          animation: none !important;
        }
      }
    `;
    document.head.appendChild(style);

    const progress = document.createElement("aside");
    progress.id = "hydro-progress";
    progress.dataset.busy = "0";
    progress.setAttribute("aria-label", "实时进度");
    progress.innerHTML = `
      <header class="hydro-side-head">
        <span class="hydro-side-mark" aria-hidden="true"></span>
        <div>
          <p class="eyebrow">实时进度</p>
          <p id="hydro-progress-title">待命</p>
        </div>
        <span id="hydro-progress-phase" class="hydro-chip" data-tone="idle">待命</span>
      </header>
      <div class="hydro-track" aria-hidden="true"><span id="hydro-progress-bar"></span></div>
      <p id="hydro-progress-detail">点击图上的「用户」或「任务」输入参数</p>
      <ol id="hydro-progress-steps" aria-label="流程步骤"></ol>
      <div id="hydro-llm-wrap" hidden>
        <p class="eyebrow">大模型流式输出</p>
        <pre id="hydro-llm" aria-live="polite"></pre>
      </div>
    `;
    document.body.appendChild(progress);

    const results = document.createElement("aside");
    results.id = "hydro-results";
    results.hidden = true;
    results.setAttribute("aria-label", "最终结果");
    results.innerHTML = `
      <header class="hydro-side-head">
        <span class="hydro-side-mark" aria-hidden="true"></span>
        <div>
          <p class="eyebrow">评估结果</p>
          <h2 class="hydro-side-title">最终结果</h2>
        </div>
        <button id="hydro-results-close" type="button" aria-label="关闭结果面板">关闭</button>
      </header>
      <div id="hydro-results-scroll">
        <div id="hydro-results-body"></div>
        <p class="section-title">智能体全程日志</p>
        <div id="hydro-agent-log"></div>
      </div>
    `;
    document.body.appendChild(results);

    const panel = document.createElement("section");
    panel.id = "hydro-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <h2>第一步 · 输入任务</h2>
      <p class="hint">点 Archify 图上的「用户 / 任务」打开。真实模式会调 SiliconFlow，并跑 XAJ，通常比演示慢。</p>
      <div class="grid">
        <label>流域
          <input id="hydro-basin" value="camels_13235000" autocomplete="off" />
        </label>
        <label>开始日期
          <input id="hydro-start-date" type="date" value="2020-04-29" />
        </label>
        <label>结束日期
          <input id="hydro-end" type="date" value="2020-05-01" />
        </label>
        <label>Forcing
          <select id="hydro-forcing">
            <option value="R" selected>R · 实测强迫</option>
            <option value="F">F · 预报强迫</option>
          </select>
        </label>
        <label class="check">
          <input id="hydro-optimize" type="checkbox" checked />
          允许有限调参
        </label>
      </div>
      <div class="actions">
        <button id="hydro-run" type="button">开始运行</button>
        <button id="hydro-cancel" type="button">取消</button>
      </div>
      <p id="hydro-status"></p>
    `;
    document.body.appendChild(panel);

    $("hydro-run").addEventListener("click", () => {
      if (polling) {
        clearInterval(polling);
        polling = null;
      }
      void startRun();
    });
    $("hydro-cancel").addEventListener("click", () => {
      closeInputPanel();
      setProgress({
        title: "待命",
        detail: "点击图上的「用户」或「任务」输入参数",
        busy: false,
        steps: [],
      });
    });
    $("hydro-results-close")?.addEventListener("click", () => closeResultsPanel());
  }

  function bindDiagramClicks() {
    document.addEventListener(
      "click",
      (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        if (target.closest("#hydro-panel") || target.closest("#hydro-progress") || target.closest("#hydro-results")) return;
        const node = target.closest("[data-node-id]");
        if (!node) return;
        const id = node.getAttribute("data-node-id");
        if (id === "user" || id === "task") {
          event.preventDefault();
          event.stopPropagation();
          openInputPanel();
        }
      },
      true,
    );
  }

  function quietArchify() {
    const params = new URLSearchParams(location.search);
    let changed = false;
    if (params.get("theme") !== "light") {
      params.set("theme", "light");
      changed = true;
    }
    if (params.has("play")) {
      params.delete("play");
      changed = true;
    }
    if (params.get("present") === "1") {
      params.delete("present");
      changed = true;
    }
    if (changed) {
      const q = params.toString();
      location.replace(`${location.pathname}${q ? `?${q}` : ""}${location.hash || ""}`);
      return false;
    }
    document.documentElement.setAttribute("data-theme", "light");
    document.documentElement.setAttribute("data-motion", "still");
    if (location.hash && /view=|focus=/.test(location.hash)) {
      history.replaceState(null, "", location.pathname + location.search);
    }
    return true;
  }

  function boot() {
    if (!quietArchify()) return;
    mountUi();
    bindDiagramClicks();
    highlight("user");
    setProgress({
      title: "待命",
      detail: "点击图上的「用户」或「任务」输入参数",
      busy: false,
      steps: [],
    });
    void fetch("/api/health")
      .then((r) => r.json())
      .then((h) => {
        if (h.mode === "real") {
          setProgress({
            title: "真实模式就绪",
            detail: `${h.provider_model || "SiliconFlow"} + XAJ · 点「用户」开始`,
            busy: false,
            steps: [],
          });
        } else {
          setProgress({
            title: "演示模式",
            detail: "未检测到真实 LLM/数据 · 点「用户」开始",
            busy: false,
            steps: [],
          });
        }
      })
      .catch(() => {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
