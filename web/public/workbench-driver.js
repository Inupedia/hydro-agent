/**
 * Hydro-Agent Archify workbench driver.
 * Click「用户/任务」to input; live progress panel shows the current step.
 */
(function () {
  const ACTION_NODE = {
    A01_CHECK_DATA: "task",
    A03_VALIDATE_SCHEME: "task",
    A05_FORECAST: "forecast",
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

  function setProgress({ title, detail, busy, steps, llmText, llmStreaming }) {
    const titleEl = $("hydro-progress-title");
    const detailEl = $("hydro-progress-detail");
    const listEl = $("hydro-progress-steps");
    const panel = $("hydro-progress");
    const llmEl = $("hydro-llm");
    const llmWrap = $("hydro-llm-wrap");
    if (panel) panel.dataset.busy = busy ? "1" : "0";
    if (titleEl) titleEl.textContent = title || "待命";
    if (detailEl) detailEl.textContent = detail || "";
    if (listEl && Array.isArray(steps)) {
      listEl.innerHTML = steps
        .map((s) => `<li data-state="${s.state}">${escapeHtml(s.text)}</li>`)
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
      if (body) {
        body.innerHTML = `
          <p class="story">${escapeHtml(results.story_zh || "流程已完成。")}</p>
          <dl>
            <div><dt>任务</dt><dd>${escapeHtml(results.task_id)}</dd></div>
            <div><dt>阶段</dt><dd>${escapeHtml(results.phase_zh || results.phase)}</dd></div>
            <div><dt>方案</dt><dd>${escapeHtml(scheme.scheme_id || "—")}（${escapeHtml(scheme.status || "—")}）</dd></div>
            <div><dt>Gate</dt><dd>${escapeHtml(gate ? GATE_ZH[gate.status] || gate.status : "无")}</dd></div>
            <div><dt>NSE / KGE</dt><dd>${fmtMetric(metrics.NSE)} / ${fmtMetric(metrics.KGE)}</dd></div>
            <div><dt>MAE / Bias</dt><dd>${fmtMetric(metrics.MAE)} / ${fmtMetric(metrics.Bias)}</dd></div>
            <div><dt>预报摘要</dt><dd>${leadBits || "无"}</dd></div>
            <div><dt>报告</dt><dd>${
              reports.length
                ? reports
                    .map(
                      (name) =>
                        `<a href="/api/tasks/${encodeURIComponent(id)}/report/${encodeURIComponent(name)}" target="_blank" rel="noreferrer">${escapeHtml(name)}</a>`,
                    )
                    .join(" · ")
                : "无"
            }</dd></div>
            <div><dt>日志文件</dt><dd><a href="/api/tasks/${encodeURIComponent(id)}/report/agent-log.jsonl" target="_blank" rel="noreferrer">agent-log.jsonl</a></dd></div>
          </dl>
        `;
      }
      const rounds = agentLog.rounds || [];
      if (logEl) {
        if (!rounds.length) {
          logEl.innerHTML = "<p>暂无智能体轮次日志。</p>";
        } else {
          logEl.innerHTML = rounds
            .map((round) => {
              const obs = (round.tool_observations || []).map(escapeHtml).join("；") || "—";
              const metricsText = Object.entries(round.tool_metrics || {})
                .map(([k, v]) => `${escapeHtml(k)}=${fmtMetric(v)}`)
                .join("，");
              return `
                <article class="round">
                  <header>第 ${round.round_number} 轮 · ${escapeHtml(round.action_zh || round.action || "决策")} · ${escapeHtml(round.tool_status_zh || round.tool_status || "待执行")}</header>
                  <p><strong>输入摘要：</strong>${escapeHtml(round.input_summary_zh || "—")}</p>
                  <p><strong>假设：</strong>${escapeHtml(round.hypothesis_zh || round.hypothesis || "—")}
                     · <strong>理由：</strong>${escapeHtml(round.rationale_summary || "—")}</p>
                  <details>
                    <summary>模型原始输出</summary>
                    <pre>${escapeHtml(round.llm_output || "（无）")}</pre>
                  </details>
                  <details>
                    <summary>本轮 WorldState 输入 JSON</summary>
                    <pre>${escapeHtml(JSON.stringify(round.input_world_state || {}, null, 2))}</pre>
                  </details>
                  <p><strong>工具观测：</strong>${obs}</p>
                  <p><strong>工具指标：</strong>${metricsText || "—"}</p>
                  ${round.error ? `<p class="err"><strong>错误：</strong>${escapeHtml(round.error)}</p>` : ""}
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
        return { state: "current", text: `▶ ${name}（进行中）` };
      }
      if (done.has(code)) {
        const item = [...timeline].reverse().find((t) => t.action === code);
        const label = item?.label || name;
        return { state: "done", text: `✓ ${label}` };
      }
      return { state: "todo", text: `○ ${name}` };
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
      [data-node-id="user"],
      [data-node-id="task"] { cursor: pointer !important; }
      [data-node-id].hydro-active {
        filter: drop-shadow(0 0 0.55rem rgba(31, 107, 74, 0.95));
        outline: 3px solid #1f6b4a;
        outline-offset: 4px;
      }
      [data-node-id].hydro-done { opacity: 0.92; }
      #hydro-progress {
        position: fixed;
        top: 12px;
        left: 12px;
        z-index: 2147483646;
        width: min(340px, calc(100vw - 24px));
        padding: 0.9rem 1rem;
        border-radius: 14px;
        background: rgba(255,255,255,0.97);
        border: 1px solid rgba(16,35,28,0.14);
        box-shadow: 0 12px 32px rgba(16,35,28,0.12);
        font: 13px/1.45 "IBM Plex Sans", "Segoe UI", sans-serif;
        color: #10231c;
      }
      #hydro-progress[data-busy="1"] {
        border-color: rgba(31, 107, 74, 0.45);
        box-shadow: 0 0 0 3px rgba(31, 107, 74, 0.12), 0 12px 32px rgba(16,35,28,0.12);
      }
      #hydro-progress .eyebrow {
        margin: 0 0 0.25rem;
        font-size: 11px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: rgba(16,35,28,0.55);
      }
      #hydro-progress-title {
        margin: 0;
        font-size: 1.05rem;
        font-weight: 700;
      }
      #hydro-progress[data-busy="1"] #hydro-progress-title::after {
        content: "";
        display: inline-block;
        width: 0.55rem;
        height: 0.55rem;
        margin-left: 0.45rem;
        border-radius: 999px;
        background: #1f6b4a;
        vertical-align: middle;
        animation: hydro-pulse 1s ease-in-out infinite;
      }
      @keyframes hydro-pulse {
        0%, 100% { opacity: 0.35; transform: scale(0.85); }
        50% { opacity: 1; transform: scale(1); }
      }
      #hydro-progress-detail {
        margin: 0.35rem 0 0.75rem;
        color: rgba(16,35,28,0.72);
        font-size: 12.5px;
      }
      #hydro-progress-steps {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: 0.35rem;
        max-height: 42vh;
        overflow: auto;
      }
      #hydro-progress-steps li {
        padding: 0.35rem 0.45rem;
        border-radius: 8px;
        background: rgba(16,35,28,0.04);
        font-size: 12px;
      }
      #hydro-progress-steps li[data-state="done"] {
        color: rgba(16,35,28,0.7);
      }
      #hydro-progress-steps li[data-state="current"] {
        background: rgba(31, 107, 74, 0.12);
        color: #14553a;
        font-weight: 600;
      }
      #hydro-progress-steps li[data-state="todo"] {
        color: rgba(16,35,28,0.4);
      }
      #hydro-llm-wrap[hidden] { display: none !important; }
      #hydro-llm-wrap[data-streaming="1"] .eyebrow::after {
        content: " · 接收中";
        color: #1f6b4a;
      }
      #hydro-llm {
        margin: 0.35rem 0 0;
        max-height: 28vh;
        overflow: auto;
        padding: 0.55rem 0.6rem;
        border-radius: 8px;
        background: #0f1a16;
        color: #d7efe4;
        font: 11.5px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
        white-space: pre-wrap;
        word-break: break-word;
      }
      #hydro-results {
        position: fixed;
        top: 12px;
        right: 12px;
        z-index: 2147483646;
        width: min(440px, calc(100vw - 24px));
        max-height: calc(100vh - 24px);
        overflow: auto;
        padding: 0.95rem 1rem 1.1rem;
        border-radius: 14px;
        background: rgba(255,255,255,0.98);
        border: 1px solid rgba(16,35,28,0.14);
        box-shadow: 0 12px 32px rgba(16,35,28,0.12);
        font: 13px/1.45 "IBM Plex Sans", "PingFang SC", "Segoe UI", sans-serif;
        color: #10231c;
      }
      #hydro-results[hidden] { display: none !important; }
      #hydro-results h2 {
        margin: 0;
        font-size: 1.05rem;
      }
      #hydro-results .story {
        margin: 0.55rem 0 0.75rem;
        color: rgba(16,35,28,0.78);
      }
      #hydro-results dl {
        margin: 0;
        display: grid;
        gap: 0.45rem;
      }
      #hydro-results dl > div {
        display: grid;
        grid-template-columns: 5.5rem 1fr;
        gap: 0.35rem;
        padding: 0.35rem 0.4rem;
        border-radius: 8px;
        background: rgba(16,35,28,0.04);
      }
      #hydro-results dt {
        color: rgba(16,35,28,0.55);
        font-size: 12px;
      }
      #hydro-results dd {
        margin: 0;
        word-break: break-word;
      }
      #hydro-results a { color: #14553a; }
      #hydro-results .section-title {
        margin: 1rem 0 0.45rem;
        font-size: 12px;
        letter-spacing: 0.04em;
        color: rgba(16,35,28,0.55);
        text-transform: uppercase;
      }
      #hydro-agent-log {
        display: grid;
        gap: 0.65rem;
      }
      #hydro-agent-log .round {
        padding: 0.55rem 0.6rem;
        border-radius: 10px;
        background: rgba(16,35,28,0.04);
        border: 1px solid rgba(16,35,28,0.08);
      }
      #hydro-agent-log .round header {
        font-weight: 700;
        margin-bottom: 0.35rem;
      }
      #hydro-agent-log .round p { margin: 0.25rem 0; }
      #hydro-agent-log details { margin: 0.35rem 0; }
      #hydro-agent-log pre {
        margin: 0.35rem 0 0;
        max-height: 180px;
        overflow: auto;
        padding: 0.45rem 0.5rem;
        border-radius: 8px;
        background: #0f1a16;
        color: #d7efe4;
        font: 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
        white-space: pre-wrap;
        word-break: break-word;
      }
      #hydro-agent-log .err, #hydro-results .err { color: #9b1c1c; }
      #hydro-results-close {
        float: right;
        border: 0;
        background: transparent;
        cursor: pointer;
        color: rgba(16,35,28,0.65);
        font: inherit;
      }
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
      #hydro-panel {
        position: fixed;
        z-index: 2147483647;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        width: min(420px, calc(100vw - 24px));
        padding: 1rem 1.1rem 1.1rem;
        border-radius: 14px;
        background: rgba(255,255,255,0.98);
        border: 1px solid rgba(16,35,28,0.16);
        box-shadow: 0 18px 48px rgba(16,35,28,0.18);
        font: 14px/1.45 "IBM Plex Sans", "Segoe UI", sans-serif;
        color: #10231c;
      }
      #hydro-panel[hidden] { display: none !important; }
      #hydro-panel h2 { margin: 0 0 0.35rem; font-size: 1.05rem; }
      #hydro-panel .hint {
        margin: 0 0 0.85rem;
        color: rgba(16,35,28,0.68);
        font-size: 12.5px;
      }
      #hydro-panel .grid { display: grid; gap: 0.65rem; }
      #hydro-panel label {
        display: grid;
        gap: 0.25rem;
        font-size: 12px;
        color: rgba(16,35,28,0.72);
      }
      #hydro-panel input,
      #hydro-panel select,
      #hydro-panel button {
        font: inherit;
        padding: 0.5rem 0.65rem;
        border-radius: 8px;
        border: 1px solid rgba(16,35,28,0.18);
        background: #fff;
        color: #10231c;
      }
      #hydro-panel .check {
        display: flex;
        align-items: center;
        gap: 0.45rem;
      }
      #hydro-panel .check input { width: 1rem; height: 1rem; padding: 0; }
      #hydro-panel .actions {
        display: flex;
        gap: 0.5rem;
        margin-top: 0.85rem;
      }
      #hydro-run {
        background: #1f6b4a !important;
        color: #fff !important;
        border: 0 !important;
        cursor: pointer;
        font-weight: 600;
        flex: 1;
      }
      #hydro-run:disabled { opacity: 0.55; cursor: not-allowed; }
      #hydro-cancel { background: transparent !important; cursor: pointer; }
      #hydro-status {
        margin: 0.75rem 0 0;
        font-size: 12.5px;
        color: rgba(16,35,28,0.75);
      }
      html[data-present="true"] .guided-views { display: none !important; }
      @media (max-width: 720px) {
        #hydro-progress {
          left: 8px;
          right: 8px;
          width: auto;
          max-height: 38vh;
        }
      }
    `;
    document.head.appendChild(style);

    const progress = document.createElement("aside");
    progress.id = "hydro-progress";
    progress.dataset.busy = "0";
    progress.innerHTML = `
      <p class="eyebrow">实时进度</p>
      <p id="hydro-progress-title">待命</p>
      <p id="hydro-progress-detail">点击图上的「用户」或「任务」输入参数</p>
      <ol id="hydro-progress-steps"></ol>
      <div id="hydro-llm-wrap" hidden>
        <p class="eyebrow" style="margin-top:0.75rem">大模型流式输出</p>
        <pre id="hydro-llm"></pre>
      </div>
    `;
    document.body.appendChild(progress);

    const results = document.createElement("aside");
    results.id = "hydro-results";
    results.hidden = true;
    results.innerHTML = `
      <button id="hydro-results-close" type="button" aria-label="关闭">关闭</button>
      <h2>最终结果</h2>
      <div id="hydro-results-body"></div>
      <p class="section-title">智能体全程日志</p>
      <div id="hydro-agent-log"></div>
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
        if (target.closest("#hydro-panel") || target.closest("#hydro-progress")) return;
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
