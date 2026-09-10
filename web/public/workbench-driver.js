/**
 * Hydro-Agent Archify workbench driver.
 * Click「用户/任务」to input; live progress panel shows the current step.
 */
(function () {
  const ACTION_NODE = {
    M01_CHECK_MATERIALS: 'materials',
  M02_DELINEATE: 'delineate',
  M03_REVIEW_BOUNDARY: 'boundary',
  M04_BUILD_INPUTS: 'inputs',
  M05_VALIDATE_PLAN: 'plan',
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
    const body = $("hydro-results-body");
    const logEl = $("hydro-agent-log");
    if (body) {
      body.innerHTML = `
        <div class="hydro-empty-state">
          <p class="hydro-empty-title">尚无结果</p>
          <p>完成评估后，指标与方案摘要会显示在这里。</p>
        </div>`;
    }
    if (logEl) logEl.innerHTML = "";
  }

  async function showFinalResults(id) {
    const body = $("hydro-results-body");
    const logEl = $("hydro-agent-log");
    if (body) body.innerHTML = '<p class="hydro-loading">正在加载结果…</p>';
    if (logEl) logEl.innerHTML = "";
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
          return `L1=${fmtMetric(leads["1"] ?? leads[1])} · L2=${fmtMetric(leads["2"] ?? leads[2])} · L3=${fmtMetric(leads["3"] ?? leads[3])}`;
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
            <div><dt>预报</dt><dd>${leadBits || "无"}</dd></div>
            <div><dt>产物</dt><dd class="hydro-links">${
              reports.length
                ? reports
                    .map(
                      (name) =>
                        `<a href="/api/tasks/${encodeURIComponent(id)}/report/${encodeURIComponent(name)}" target="_blank" rel="noreferrer">${escapeHtml(name)}</a>`,
                    )
                    .join("")
                : ""
            }<a href="/api/tasks/${encodeURIComponent(id)}/report/agent-log.jsonl" target="_blank" rel="noreferrer">agent-log.jsonl</a></dd></div>
          </dl>
        `;
      }
      const rounds = agentLog.rounds || [];
      if (logEl) {
        if (!rounds.length) {
          logEl.innerHTML = '<p class="hydro-empty">暂无轮次日志。</p>';
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
                  <p class="hydro-judgment"><span>判断</span>${escapeHtml(round.judgment_zh || round.rationale_summary || "—")}</p>
                  <p><span class="hydro-label">摘要</span>${escapeHtml(round.input_summary_zh || "—")}</p>
                  <p><span class="hydro-label">假设</span>${escapeHtml(round.hypothesis_zh || round.hypothesis || "—")}
                     <span class="hydro-label">理由</span>${escapeHtml(round.rationale_summary || "—")}</p>
                  <details>
                    <summary>模型输出</summary>
                    <pre>${escapeHtml(round.llm_output || "（无）")}</pre>
                  </details>
                  <details>
                    <summary>WorldState JSON</summary>
                    <pre>${escapeHtml(JSON.stringify(round.input_world_state || {}, null, 2))}</pre>
                  </details>
                  <p><span class="hydro-label">观测</span>${obs}</p>
                  <p><span class="hydro-label">指标</span>${metricsText || "—"}</p>
                  ${round.error ? `<p class="err"><span class="hydro-label">错误</span>${escapeHtml(round.error)}</p>` : ""}
                </article>
              `;
            })
            .join("");
        }
      }
    } catch (err) {
      console.error(err);
      if (body) body.innerHTML = `<p class="err">加载失败：${escapeHtml(String(err.message || err))}</p>`;
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
      model_plan_id: $("hydro-model-plan")?.value || null,
      allow_optimization: $("hydro-optimize").checked,
      max_agent_decision_rounds: 20,
      max_optimization_cycles: 4,
    };
  }

  function openInputPanel() {
    const panel = $("hydro-panel");
    const backdrop = $("hydro-backdrop");
    if (!panel) return;
    panel.hidden = false;
    if (backdrop) backdrop.hidden = false;
    highlight("user");
    setStatus("填写参数后点开始");
    $("hydro-basin")?.focus();
  }

  function closeInputPanel() {
    const panel = $("hydro-panel");
    const backdrop = $("hydro-backdrop");
    if (panel) panel.hidden = true;
    if (backdrop) backdrop.hidden = true;
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
            title: "已完成",
            detail: `任务 ${taskId} · 右侧为评估结果`,
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

  function setupModelBuilder() {
    let currentPlan = null;
    let planTimer = null;
    let library = [];
    const choosePlan = (p) => {
      if (!p || p.status !== "ready") return;
      $("hydro-model-plan").value = p.plan_id;
      $("hydro-basin").value = p.basin_id;
      $("hydro-start-date").value = p.suggested_start;
      $("hydro-end").value = p.suggested_end;
      $("hydro-forcing").value = "R";
    };
    const list = async () => {
      library = await api("/api/model-plans");
      const selected = $("hydro-model-plan").value;
      $("hydro-model-plan").innerHTML = '<option value="">请选择已复核方案</option>' + library.filter(p => p.status === "ready").map(p => `<option value="${escapeHtml(p.plan_id)}">腰古 · ${escapeHtml(p.plan_id)}</option>`).join("");
      $("hydro-model-plan").value = selected;
    };
    const render = async () => {
      if (!currentPlan) return;
      const p = await api(`/api/model-plans/${currentPlan}`);
      $("hydro-model-state").textContent = p.error || p.stages.map(s => `${s.label}：${({pending:"待开始",running:"执行中",completed:"已完成",awaiting_review:"待复核",failed:"失败"})[s.status] || s.status}`).join(" / ");
      highlight(ACTION_NODE[p.current_stage] || "materials");
      p.stages.filter(s => s.status === "completed").forEach(s => markDone(ACTION_NODE[s.code]));
      if (p.status === "awaiting_review") {
        clearInterval(planTimer); planTimer = null;
        const img = document.createElement("img"); img.src = `/api/model-plans/${p.plan_id}/map`; img.alt = "流域出口与边界复核地图"; img.style.width = "100%";
        const button = document.createElement("button"); button.type = "button"; button.textContent = "确认图中出口与边界，继续构建输入";
        button.onclick = async () => {
          button.disabled = true;
          try { await api(`/api/model-plans/${p.plan_id}/confirm-boundary`, {method:"POST",body:JSON.stringify({boundary_hash:p.boundary_hash})}); planTimer = setInterval(() => void render().catch(e=>setStatus(e.message)), 1500); }
          catch(e) { setStatus(e.message); button.disabled = false; }
        };
        $("hydro-model-state").append(img,button);
      }
      if (["ready","failed"].includes(p.status)) {
        clearInterval(planTimer); planTimer = null;
        $("hydro-new-model").disabled = false;
        if (p.status === "ready") { await list(); choosePlan(p); }
      }
    };
    $("hydro-model-plan").onchange = () => choosePlan(library.find(p => p.plan_id === $("hydro-model-plan").value));
    $("hydro-new-model").onclick = async () => {
      $("hydro-new-model").disabled = true; $("hydro-model-plan").value = "";
      try {
        const p = await api("/api/model-plans",{method:"POST",body:"{}"}); currentPlan = p.plan_id;
        await render(); planTimer = setInterval(() => void render().catch(e=>setStatus(e.message)),1500);
      } catch(e) { setStatus(e.message); $("hydro-new-model").disabled = false; }
    };
    void list().catch(e => { $("hydro-model-state").textContent = e.message; });
  }

  function mountUi() {
    if ($("hydro-shell")) return;

    document.documentElement.classList.add("hydro-workbench");
    document.body.classList.add("hydro-workbench-body");

    const style = document.createElement("style");
    style.id = "hydro-workbench-style";
    style.textContent = `
      html.hydro-workbench,
      html.hydro-workbench body.hydro-workbench-body {
        margin: 0 !important;
        padding: 0 !important;
        height: 100%;
        min-height: 100dvh;
        overflow: hidden;
        background: #e8e8ed !important;
        color: #1d1d1f;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
          "Helvetica Neue", "PingFang SC", "Segoe UI", sans-serif;
        -webkit-font-smoothing: antialiased;
      }

      :root {
        --macos-bg: #e8e8ed;
        --macos-sidebar: rgba(246, 246, 248, 0.82);
        --macos-surface: rgba(255, 255, 255, 0.72);
        --macos-surface-solid: #ffffff;
        --macos-fill: rgba(120, 120, 128, 0.12);
        --macos-fill-2: rgba(120, 120, 128, 0.18);
        --macos-separator: rgba(60, 60, 67, 0.18);
        --macos-label: #1d1d1f;
        --macos-secondary: rgba(60, 60, 67, 0.6);
        --macos-tertiary: rgba(60, 60, 67, 0.4);
        --macos-blue: #007aff;
        --macos-blue-soft: rgba(0, 122, 255, 0.12);
        --macos-green: #34c759;
        --macos-orange: #ff9f0a;
        --macos-red: #ff3b30;
        --macos-shadow: 0 1px 0 rgba(255,255,255,0.65) inset, 0 8px 28px rgba(0,0,0,0.08);
        --macos-radius: 12px;
        --macos-mono: ui-monospace, "SF Mono", Menlo, monospace;
      }

      #hydro-shell {
        height: 100dvh;
        display: grid;
        grid-template-rows: 44px minmax(0, 1fr);
        overflow: hidden;
      }

      #hydro-titlebar {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0 0.9rem;
        background: rgba(246, 246, 248, 0.9);
        border-bottom: 1px solid var(--macos-separator);
        backdrop-filter: saturate(180%) blur(20px);
        -webkit-backdrop-filter: saturate(180%) blur(20px);
        z-index: 5;
      }
      #hydro-titlebar .traffic {
        display: flex;
        gap: 7px;
        width: 52px;
      }
      #hydro-titlebar .traffic span {
        width: 11px;
        height: 11px;
        border-radius: 50%;
        background: var(--macos-fill-2);
      }
      #hydro-titlebar .traffic span:nth-child(1) { background: #ff5f57; }
      #hydro-titlebar .traffic span:nth-child(2) { background: #febc2e; }
      #hydro-titlebar .traffic span:nth-child(3) { background: #28c840; }
      #hydro-titlebar h1 {
        margin: 0;
        flex: 1;
        text-align: center;
        font-size: 13px;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: var(--macos-label);
      }
      #hydro-titlebar .hydro-toolbar-actions {
        display: flex;
        gap: 0.4rem;
        min-width: 52px;
        justify-content: flex-end;
      }
      #hydro-titlebar button {
        appearance: none;
        border: 0;
        min-height: 28px;
        padding: 0 0.7rem;
        border-radius: 999px;
        background: var(--macos-fill);
        color: var(--macos-label);
        font: 600 12px/1 -apple-system, BlinkMacSystemFont, sans-serif;
        cursor: pointer;
      }
      #hydro-titlebar button:hover { background: var(--macos-fill-2); }
      #hydro-titlebar button.primary {
        background: var(--macos-blue);
        color: #fff;
      }

      #hydro-body {
        display: grid;
        grid-template-columns: minmax(220px, 260px) minmax(0, 1fr) minmax(260px, 320px);
        min-height: 0;
        overflow: hidden;
      }

      #hydro-progress,
      #hydro-results {
        position: relative;
        top: auto;
        left: auto;
        right: auto;
        bottom: auto;
        width: auto !important;
        max-height: none !important;
        z-index: 1;
        display: flex;
        flex-direction: column;
        min-height: 0;
        overflow: hidden;
        background: var(--macos-sidebar);
        backdrop-filter: saturate(160%) blur(24px);
        -webkit-backdrop-filter: saturate(160%) blur(24px);
        border: 0;
        border-radius: 0;
        box-shadow: none;
        padding: 0;
      }
      #hydro-progress { border-right: 1px solid var(--macos-separator); }
      #hydro-results { border-left: 1px solid var(--macos-separator); }
      #hydro-results[hidden] { display: flex !important; }

      .hydro-pane-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
        padding: 0.85rem 0.9rem 0.55rem;
        flex: 0 0 auto;
      }
      .hydro-pane-head .eyebrow {
        margin: 0;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        color: var(--macos-tertiary);
      }
      #hydro-progress-title,
      .hydro-pane-title {
        margin: 0.15rem 0 0;
        font-size: 17px;
        font-weight: 600;
        letter-spacing: -0.02em;
        color: var(--macos-label);
        line-height: 1.25;
      }
      .hydro-chip {
        min-height: 22px;
        padding: 0 0.5rem;
        border-radius: 999px;
        background: var(--macos-fill);
        color: var(--macos-secondary);
        font-size: 11px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        border: 0;
      }
      .hydro-chip[data-tone="live"] {
        background: var(--macos-blue-soft);
        color: var(--macos-blue);
      }
      .hydro-chip[data-tone="done"] {
        background: rgba(52, 199, 89, 0.16);
        color: #248a3d;
      }

      .hydro-track {
        margin: 0 0.9rem 0.55rem;
        height: 3px;
        border-radius: 999px;
        background: var(--macos-fill);
        overflow: hidden;
        flex: 0 0 auto;
      }
      #hydro-progress-bar {
        display: block;
        height: 100%;
        width: 0%;
        background: var(--macos-blue);
        border-radius: inherit;
        transition: width 200ms ease;
      }
      #hydro-progress-detail {
        margin: 0;
        padding: 0 0.9rem 0.7rem;
        color: var(--macos-secondary);
        font-size: 12px;
        line-height: 1.45;
        flex: 0 0 auto;
      }

      #hydro-progress-steps {
        list-style: none;
        margin: 0;
        padding: 0 0.55rem 0.75rem;
        overflow: auto;
        flex: 1 1 auto;
        min-height: 0;
        display: grid;
        gap: 2px;
        scrollbar-width: thin;
      }
      #hydro-progress-steps li {
        display: grid;
        grid-template-columns: 14px 1fr auto;
        align-items: center;
        gap: 0.55rem;
        min-height: 32px;
        padding: 0.35rem 0.55rem;
        border-radius: 8px;
        font-size: 12px;
        color: var(--macos-secondary);
        position: relative;
      }
      #hydro-progress-steps li::before {
        content: "";
        position: absolute;
        left: calc(0.55rem + 6px);
        top: -2px;
        bottom: -2px;
        width: 1px;
        background: var(--macos-separator);
      }
      #hydro-progress-steps li:first-child::before { top: 50%; }
      #hydro-progress-steps li:last-child::before { bottom: 50%; }
      .hydro-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        border: 1.5px solid rgba(60,60,67,0.28);
        background: #fff;
        z-index: 1;
        justify-self: center;
      }
      .hydro-step-text { min-width: 0; line-height: 1.3; }
      .hydro-step-state {
        font-size: 10px;
        color: var(--macos-tertiary);
        font-variant-numeric: tabular-nums;
      }
      #hydro-progress-steps li[data-state="done"] { color: var(--macos-label); }
      #hydro-progress-steps li[data-state="done"] .hydro-dot {
        border-color: var(--macos-blue);
        background: var(--macos-blue);
        box-shadow: inset 0 0 0 1.5px #fff;
      }
      #hydro-progress-steps li[data-state="done"] .hydro-step-state { color: var(--macos-blue); }
      #hydro-progress-steps li[data-state="current"] {
        background: var(--macos-blue-soft);
        color: var(--macos-blue);
        font-weight: 600;
      }
      #hydro-progress-steps li[data-state="current"] .hydro-dot {
        border-color: var(--macos-blue);
        background: #fff;
        box-shadow: 0 0 0 3px rgba(0,122,255,0.18);
      }
      #hydro-progress-steps li[data-state="current"] .hydro-step-state { color: var(--macos-blue); }
      #hydro-progress-steps li[data-state="todo"] { opacity: 0.72; }

      #hydro-llm-wrap {
        flex: 0 0 auto;
        margin: 0 0.7rem 0.8rem;
        padding-top: 0.55rem;
        border-top: 1px solid var(--macos-separator);
      }
      #hydro-llm-wrap[hidden] { display: none !important; }
      #hydro-llm-wrap .eyebrow {
        margin: 0 0 0.35rem;
        font-size: 11px;
        font-weight: 600;
        color: var(--macos-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.02em;
      }
      #hydro-llm-wrap[data-streaming="1"] .eyebrow::after {
        content: " · 接收中";
        color: var(--macos-blue);
        text-transform: none;
      }
      #hydro-llm {
        margin: 0;
        max-height: 22vh;
        overflow: auto;
        padding: 0.6rem 0.65rem;
        border-radius: 10px;
        background: #1c1c1e;
        color: #f5f5f7;
        font: 11px/1.45 var(--macos-mono);
        white-space: pre-wrap;
        word-break: break-word;
      }

      #hydro-stage {
        min-width: 0;
        min-height: 0;
        overflow: auto;
        background:
          radial-gradient(1200px 600px at 50% -10%, rgba(255,255,255,0.75), transparent 60%),
          #f5f5f7;
        position: relative;
      }
      #hydro-stage .toolbar,
      #hydro-stage .guided-views,
      #hydro-stage .cards,
      #hydro-stage .share-chapter-cue,
      #hydro-stage .diagram-guide,
      #hydro-stage .semantic-lens,
      #hydro-stage .node-finder,
      #hydro-stage .route-probe,
      #hydro-stage .semantic-passport,
      #hydro-stage .overview-map,
      #hydro-stage .overview-map-feedback {
        display: none !important;
      }
      #hydro-stage .header-row::after { display: none !important; }
      #hydro-stage .pulse-dot { display: none !important; }
      #hydro-stage .container {
        max-width: none !important;
        width: 100% !important;
        margin: 0 !important;
        padding: 0.75rem 0.85rem 1.25rem !important;
      }
      #hydro-stage .header {
        margin: 0 0 0.65rem !important;
      }
      #hydro-stage .header h1 {
        font-family: inherit !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        letter-spacing: -0.015em !important;
        color: var(--macos-label) !important;
      }
      #hydro-stage .diagram-container {
        border-radius: 14px;
        background: rgba(255,255,255,0.78);
        border: 1px solid var(--macos-separator);
        box-shadow: var(--macos-shadow);
        overflow: hidden;
      }
      #hydro-stage body,
      html.hydro-workbench body {
        background: transparent !important;
      }

      [data-node-id="user"],
      [data-node-id="task"] { cursor: pointer !important; }
      [data-node-id].hydro-active {
        filter: drop-shadow(0 0 0.45rem rgba(0, 122, 255, 0.85));
        outline: 2px solid var(--macos-blue);
        outline-offset: 3px;
      }
      [data-node-id].hydro-done { opacity: 0.94; }

      #hydro-results-scroll {
        overflow: auto;
        padding: 0 0.75rem 0.9rem;
        display: grid;
        gap: 0.65rem;
        min-height: 0;
        flex: 1 1 auto;
        scrollbar-width: thin;
      }
      .hydro-empty-state {
        margin-top: 0.35rem;
        padding: 1rem 0.85rem;
        border-radius: 12px;
        background: rgba(255,255,255,0.55);
        border: 1px solid var(--macos-separator);
        color: var(--macos-secondary);
        font-size: 12px;
        line-height: 1.45;
      }
      .hydro-empty-title {
        margin: 0 0 0.25rem;
        color: var(--macos-label);
        font-size: 14px;
        font-weight: 600;
      }
      .hydro-loading {
        margin: 0;
        color: var(--macos-secondary);
        font-size: 12px;
      }
      #hydro-results .story {
        margin: 0;
        padding: 0.7rem 0.75rem;
        border-radius: 12px;
        background: rgba(255,255,255,0.7);
        border: 1px solid var(--macos-separator);
        color: var(--macos-label);
        font-size: 12.5px;
        line-height: 1.5;
      }
      .hydro-metric-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.45rem;
      }
      .hydro-metric {
        padding: 0.65rem 0.7rem;
        border-radius: 12px;
        background: rgba(255,255,255,0.75);
        border: 1px solid var(--macos-separator);
        display: grid;
        gap: 0.15rem;
      }
      .hydro-metric span {
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--macos-tertiary);
      }
      .hydro-metric strong {
        font-size: 18px;
        font-weight: 600;
        letter-spacing: -0.03em;
        font-variant-numeric: tabular-nums;
        color: var(--macos-label);
      }
      .hydro-gate-banner {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        min-height: 36px;
        padding: 0.45rem 0.7rem;
        border-radius: 10px;
        background: rgba(255,255,255,0.7);
        border: 1px solid var(--macos-separator);
      }
      .hydro-gate-label {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--macos-tertiary);
      }
      .hydro-gate-banner strong { font-size: 13px; }
      .hydro-gate-banner[data-gate="ACCEPT"] {
        background: rgba(52, 199, 89, 0.12);
        border-color: rgba(52, 199, 89, 0.28);
        color: #248a3d;
      }
      .hydro-gate-banner[data-gate="ROLLBACK"] {
        background: rgba(255, 159, 10, 0.14);
        border-color: rgba(255, 159, 10, 0.3);
        color: #9a6700;
      }
      .hydro-kv {
        margin: 0;
        display: grid;
        gap: 0.35rem;
      }
      .hydro-kv > div {
        display: grid;
        grid-template-columns: 3.4rem 1fr;
        gap: 0.4rem;
        padding: 0.4rem 0.5rem;
        border-radius: 8px;
        background: rgba(255,255,255,0.45);
      }
      .hydro-kv dt {
        color: var(--macos-tertiary);
        font-size: 11px;
        font-weight: 600;
      }
      .hydro-kv dd {
        margin: 0;
        font-size: 12px;
        word-break: break-word;
        display: flex;
        flex-wrap: wrap;
        gap: 0.3rem 0.45rem;
        align-items: baseline;
      }
      .hydro-kv code {
        font-family: var(--macos-mono);
        font-size: 10.5px;
        background: var(--macos-fill);
        padding: 0.1rem 0.3rem;
        border-radius: 5px;
      }
      .hydro-kv em {
        font-style: normal;
        color: var(--macos-secondary);
        font-size: 11px;
      }
      .hydro-links {
        display: flex !important;
        flex-wrap: wrap;
        gap: 0.35rem;
      }
      .hydro-links a,
      #hydro-results a {
        color: var(--macos-blue);
        text-decoration: none;
        font-weight: 500;
      }
      .hydro-links a:hover { text-decoration: underline; }
      .section-title {
        margin: 0.15rem 0 0;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--macos-tertiary);
      }
      #hydro-agent-log { display: grid; gap: 0.5rem; }
      #hydro-agent-log .round {
        padding: 0.65rem 0.7rem;
        border-radius: 12px;
        background: rgba(255,255,255,0.72);
        border: 1px solid var(--macos-separator);
        display: grid;
        gap: 0.3rem;
      }
      #hydro-agent-log .round[data-tone="ok"] { box-shadow: inset 3px 0 0 var(--macos-green); }
      #hydro-agent-log .round[data-tone="warn"] { box-shadow: inset 3px 0 0 var(--macos-orange); }
      #hydro-agent-log .round[data-tone="bad"] { box-shadow: inset 3px 0 0 var(--macos-red); }
      #hydro-agent-log .round header {
        display: flex;
        justify-content: space-between;
        gap: 0.5rem;
        margin: 0;
      }
      #hydro-agent-log .round header strong {
        display: block;
        font-size: 13px;
        letter-spacing: -0.01em;
      }
      .hydro-round-index {
        display: block;
        font-size: 10px;
        color: var(--macos-tertiary);
        font-weight: 600;
        margin-bottom: 0.1rem;
      }
      .hydro-status-pill {
        flex: 0 0 auto;
        min-height: 22px;
        padding: 0 0.45rem;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 700;
        background: var(--macos-fill);
        color: var(--macos-secondary);
        display: inline-flex;
        align-items: center;
      }
      .hydro-status-pill[data-tone="ok"] {
        background: rgba(52, 199, 89, 0.16);
        color: #248a3d;
      }
      .hydro-status-pill[data-tone="warn"] {
        background: rgba(255, 159, 10, 0.16);
        color: #9a6700;
      }
      .hydro-status-pill[data-tone="bad"] {
        background: rgba(255, 59, 48, 0.14);
        color: #d70015;
      }
      .hydro-judgment {
        margin: 0;
        padding: 0.45rem 0.55rem;
        border-radius: 8px;
        background: var(--macos-blue-soft);
        font-size: 12px;
        line-height: 1.4;
      }
      .hydro-judgment span,
      .hydro-label {
        display: inline-block;
        margin-right: 0.3rem;
        color: var(--macos-tertiary);
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.03em;
      }
      #hydro-agent-log .round p {
        margin: 0;
        font-size: 12px;
        line-height: 1.4;
        color: var(--macos-label);
      }
      #hydro-agent-log details {
        margin: 0.1rem 0;
        border-radius: 8px;
        background: var(--macos-fill);
        padding: 0.1rem 0.4rem;
      }
      #hydro-agent-log summary {
        cursor: pointer;
        font-size: 11px;
        color: var(--macos-secondary);
        font-weight: 600;
        min-height: 28px;
        display: flex;
        align-items: center;
      }
      #hydro-agent-log pre {
        margin: 0.2rem 0 0.4rem;
        max-height: 160px;
        overflow: auto;
        padding: 0.5rem 0.55rem;
        border-radius: 8px;
        background: #1c1c1e;
        color: #f5f5f7;
        font: 10.5px/1.4 var(--macos-mono);
        white-space: pre-wrap;
        word-break: break-word;
      }
      #hydro-agent-log .err,
      #hydro-results .err { color: var(--macos-red); }
      .hydro-empty { margin: 0; color: var(--macos-secondary); font-size: 12px; }

      #hydro-backdrop {
        position: fixed;
        inset: 0;
        z-index: 2147483646;
        background: rgba(0,0,0,0.28);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
      }
      #hydro-backdrop[hidden] { display: none !important; }

      #hydro-panel {
        position: fixed;
        z-index: 2147483647;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        width: min(400px, calc(100vw - 28px));
        padding: 1rem 1.05rem 1.05rem;
        border-radius: 16px;
        background: rgba(246, 246, 248, 0.92);
        border: 1px solid rgba(255,255,255,0.55);
        box-shadow: 0 24px 64px rgba(0,0,0,0.22);
        backdrop-filter: saturate(180%) blur(28px);
        -webkit-backdrop-filter: saturate(180%) blur(28px);
        color: var(--macos-label);
      }
      #hydro-panel[hidden] { display: none !important; }
      #hydro-panel h2 {
        margin: 0 0 0.25rem;
        font-size: 17px;
        font-weight: 600;
        letter-spacing: -0.02em;
        text-align: center;
      }
      #hydro-panel .hint {
        margin: 0 0 0.9rem;
        color: var(--macos-secondary);
        font-size: 12px;
        line-height: 1.45;
        text-align: center;
      }
      #hydro-panel .grid { display: grid; gap: 0.65rem; }
      #hydro-panel label {
        display: grid;
        gap: 0.28rem;
        font-size: 12px;
        color: var(--macos-secondary);
        font-weight: 600;
      }
      #hydro-panel input,
      #hydro-panel select,
      #hydro-panel button {
        font: inherit;
        min-height: 34px;
        padding: 0.45rem 0.65rem;
        border-radius: 8px;
        border: 1px solid var(--macos-separator);
        background: rgba(255,255,255,0.92);
        color: var(--macos-label);
      }
      #hydro-panel .check {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        min-height: 34px;
      }
      #hydro-panel .check input { width: 1rem; height: 1rem; min-height: 0; padding: 0; }
      #hydro-panel .actions {
        display: flex;
        gap: 0.5rem;
        margin-top: 0.9rem;
      }
      #hydro-run {
        background: var(--macos-blue) !important;
        color: #fff !important;
        border: 0 !important;
        cursor: pointer;
        font-weight: 600;
        flex: 1;
        border-radius: 999px !important;
      }
      #hydro-run:disabled { opacity: 0.45; cursor: not-allowed; }
      #hydro-cancel {
        background: var(--macos-fill) !important;
        border: 0 !important;
        cursor: pointer;
        border-radius: 999px !important;
        min-width: 72px;
      }
      #hydro-status {
        margin: 0.7rem 0 0;
        font-size: 12px;
        color: var(--macos-secondary);
        text-align: center;
        line-height: 1.4;
      }

      #hydro-progress:focus-within,
      #hydro-results:focus-within,
      #hydro-panel:focus-within {
        outline: none;
      }
      #hydro-run:focus-visible,
      #hydro-cancel:focus-visible,
      #hydro-start-task:focus-visible,
      #hydro-panel input:focus-visible,
      #hydro-panel select:focus-visible {
        outline: 3px solid rgba(0,122,255,0.35);
        outline-offset: 1px;
      }

      @media (max-width: 1100px) {
        #hydro-body {
          grid-template-columns: minmax(200px, 230px) minmax(0, 1fr);
          grid-template-rows: minmax(0, 1fr) minmax(220px, 34vh);
        }
        #hydro-results {
          grid-column: 1 / -1;
          border-left: 0;
          border-top: 1px solid var(--macos-separator);
        }
      }
      @media (max-width: 760px) {
        #hydro-titlebar .traffic { display: none; }
        #hydro-body {
          grid-template-columns: 1fr;
          grid-template-rows: minmax(160px, 28vh) minmax(0, 1fr) minmax(180px, 32vh);
        }
        #hydro-progress {
          border-right: 0;
          border-bottom: 1px solid var(--macos-separator);
        }
        #hydro-results {
          grid-column: auto;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        #hydro-progress-bar { transition: none !important; }
      }
    `;
    document.head.appendChild(style);

    const existing = Array.from(document.body.childNodes);

    const shell = document.createElement("div");
    shell.id = "hydro-shell";

    const titlebar = document.createElement("header");
    titlebar.id = "hydro-titlebar";
    titlebar.innerHTML = `
      <div class="traffic" aria-hidden="true"><span></span><span></span><span></span></div>
      <h1>Hydro-Agent</h1>
      <div class="hydro-toolbar-actions">
        <button id="hydro-start-task" type="button" class="primary">新建任务</button>
      </div>
    `;

    const body = document.createElement("div");
    body.id = "hydro-body";

    const progress = document.createElement("aside");
    progress.id = "hydro-progress";
    progress.dataset.busy = "0";
    progress.setAttribute("aria-label", "实时进度");
    progress.innerHTML = `
      <div class="hydro-pane-head">
        <div>
          <p class="eyebrow">实时进度</p>
          <p id="hydro-progress-title">待命</p>
        </div>
        <span id="hydro-progress-phase" class="hydro-chip" data-tone="idle">待命</span>
      </div>
      <div class="hydro-track" aria-hidden="true"><span id="hydro-progress-bar"></span></div>
      <p id="hydro-progress-detail">点「新建任务」或图上的「用户 / 任务」开始</p>
      <ol id="hydro-progress-steps" aria-label="流程步骤"></ol>
      <div id="hydro-llm-wrap" hidden>
        <p class="eyebrow">模型输出</p>
        <pre id="hydro-llm" aria-live="polite"></pre>
      </div>
    `;

    const stage = document.createElement("main");
    stage.id = "hydro-stage";
    stage.setAttribute("aria-label", "流程示意图");
    existing.forEach((node) => stage.appendChild(node));

    const results = document.createElement("aside");
    results.id = "hydro-results";
    results.setAttribute("aria-label", "评估结果");
    results.innerHTML = `
      <div class="hydro-pane-head">
        <div>
          <p class="eyebrow">评估结果</p>
          <p class="hydro-pane-title">结果</p>
        </div>
      </div>
      <div id="hydro-results-scroll">
        <div id="hydro-results-body"></div>
        <p class="section-title">智能体日志</p>
        <div id="hydro-agent-log"></div>
      </div>
    `;

    body.append(progress, stage, results);
    shell.append(titlebar, body);
    document.body.appendChild(shell);

    const backdrop = document.createElement("div");
    backdrop.id = "hydro-backdrop";
    backdrop.hidden = true;
    document.body.appendChild(backdrop);

    const panel = document.createElement("section");
    panel.id = "hydro-panel";
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", "hydro-panel-title");
    panel.innerHTML = `
      <h2 id="hydro-panel-title">新建任务</h2>
      <p class="hint">填写流域与验证窗口后开始。真实模式会调用 SiliconFlow 并运行 XAJ。</p>
      <section id="hydro-model-builder">
        <label>完整模型方案<select id="hydro-model-plan"><option value="">请选择已复核方案</option></select></label>
        <button id="hydro-new-model" type="button">新建腰古流域模型</button>
        <p>DEM → 流域边界 → 面雨量 → 完整方案。集总式，预热 365 天。</p>
        <div id="hydro-model-state" role="status"></div>
      </section>
      <div class="grid">
        <label>流域
          <input id="hydro-basin" value="yaogu" autocomplete="off" />
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

    setupModelBuilder();
    closeResultsPanel();

    $("hydro-start-task")?.addEventListener("click", () => openInputPanel());
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
        detail: "点「新建任务」或图上的「用户 / 任务」开始",
        busy: false,
        steps: [],
      });
    });
    backdrop.addEventListener("click", () => closeInputPanel());
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
    document.documentElement.setAttribute("data-present", "true");
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
      detail: "点「新建任务」或图上的「用户 / 任务」开始",
      busy: false,
      steps: [],
    });
    void fetch("/api/health")
      .then((r) => r.json())
      .then((h) => {
        if (h.mode === "real") {
          setProgress({
            title: "真实模式就绪",
            detail: `${h.provider_model || "SiliconFlow"} + XAJ`,
            busy: false,
            steps: [],
          });
        } else {
          setProgress({
            title: "演示模式",
            detail: "未检测到真实 LLM/数据",
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
