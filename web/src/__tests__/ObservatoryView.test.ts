import { DOMWrapper, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ObservatoryView from "../views/ObservatoryView.vue";
import ModelPreparation from "../components/ModelPreparation.vue";
import { useDemoStore } from "../stores/demo";
import { api } from "../api/client";
import { DEMO_PRESET } from "../demo/preset";

function portal(testId: string) {
  return document.body.querySelector(
    `[data-test="${testId}"]`,
  ) as HTMLElement | null;
}

vi.mock("../components/HydrographComparisonChart.vue", () => ({
  default: { template: '<div data-test="hydrograph" />' },
}));
vi.mock("../components/ModelPreparation.vue", () => ({
  default: {
    name: "ModelPreparation",
    emits: ["selected"],
    template: "<div />",
  },
}));
vi.mock("../components/ResearchEvidencePanel.vue", () => ({
  default: {
    props: ["taskId"],
    template: '<div data-test="research-evidence-panel">research</div>',
  },
}));
vi.mock("../api/client", () => ({
  api: {
    health: vi.fn(async () => ({
      status: "ok",
      mode: "demo",
      basin_catalog: true,
    })),
    listBasins: vi.fn(async () => [
      { basin_id: "yaogu", label: "腰古", ready_for_build: true },
      {
        basin_id: "usgs_02472000",
        label: "Leaf River near Collins (MS)",
        ready_for_build: true,
      },
    ]),
    listTasks: vi.fn(async () => []),
    createTask: vi.fn(async () => ({ task_id: "test-task" })),
    deleteTask: vi.fn(async () => undefined),
    startRun: vi.fn(async () => ({ status: "running", worker_active: true })),
    getRun: vi.fn(async () => ({ status: "running", worker_active: true })),
    getTimeline: vi.fn(async () => []),
    getAgentLog: vi.fn(async () => ({ task_id: "test-task", rounds: [] })),
    getResearch: vi.fn(async () => ({
      task_id: "test-task",
      protocol: {},
      latest_experiment_plan: null,
      trials: [],
      final_test_evidence: null,
      final_test_audit: {
        consumed: false,
        read_only: false,
        single_use: false,
      },
      contracts: {
        rolling_continuous_separated: true,
        final_test_used_for_selection: false,
        trial_ledger_source: "persisted_evidence",
        objective_alias: "composite->kge",
      },
    })),
    getExperienceSummary: vi.fn(async () => ({
      current_version: 4,
      current_skill_hash: "e".repeat(64),
      status: "converging",
      active_count: 1,
      high_confidence_count: 1,
      candidate_count: 0,
      version_count: 4,
      reason: "recent_window_is_dominated_by_state_optimization",
    })),
    listExperienceEntries: vi.fn(async () => [{
      experience_id: "EXP-XAJ-0018",
      revision: 2,
      category: "model",
      scope: { model_ids: ["xaj"], basin_ids: ["yaogu"] },
      pattern: {},
      decision: {},
      supporting_evidence: [],
      contradicting_evidence: [],
      confidence: 0.86,
      status: "active",
    }]),
    listExperienceEvolution: vi.fn(async () => []),
    listExperienceVersions: vi.fn(async () => [{
      version: 4,
      status: "promoted",
      skill_hash: "e".repeat(64),
      manifest: {},
      created_at: "2026-09-18T00:00:00Z",
    }]),
    getExperienceRegression: vi.fn(async () => ({ items: [] })),
    getExperienceEntry: vi.fn(async () => ({
      experience_id: "EXP-XAJ-0018",
      revision: 2,
      category: "model",
      scope: { model_ids: ["xaj"], basin_ids: ["yaogu"] },
      pattern: {},
      decision: {},
      supporting_evidence: [],
      contradicting_evidence: [],
      confidence: 0.86,
      status: "active",
      revisions: [],
    })),
    getExperienceVersionDiff: vi.fn(async () => ({
      version: 4,
      added: [],
      modified: [],
      superseded: [],
      split: [],
      merged: [],
    })),
    getTask: vi.fn(async () => ({
      basin_id: "basin-restored",
      start_date: "2021-01-01",
      end_date: "2021-01-03",
      forcing_mode: "R",
    })),
  },
}));

async function setup(path = "/") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: ObservatoryView }],
  });
  await router.push(path);
  const wrapper = mount(ObservatoryView, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router, store: useDemoStore() };
}

beforeEach(() => {
  sessionStorage.clear();
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("single page observatory", () => {
  it("starts only on submit and stays on the same page", async () => {
    const { wrapper, router } = await setup();
    expect(api.startRun).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("模拟演示");
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(api.createTask).toHaveBeenCalledTimes(1);
    expect(api.startRun).toHaveBeenCalledTimes(1);
    expect(router.currentRoute.value.path).toBe("/");
    expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(true);
    expect(portal("run-notice")).toBeNull();
    expect(wrapper.find(".water-scene").exists()).toBe(false);
    expect(wrapper.find("fieldset").attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("submits agent evolution as an explicit opt-in", async () => {
    const { wrapper, store } = await setup();
    const toggle = wrapper.get('[data-test="agent-evolution-toggle"]');
    expect((toggle.element as HTMLInputElement).checked).toBe(false);
    expect(store.draft.agent_evolution_enabled).toBe(false);

    await toggle.setValue(true);
    expect(store.draft.agent_evolution_enabled).toBe(true);

    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(api.createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        agent_evolution_enabled: true,
      }),
    );
    wrapper.unmount();
  });

  it("opens the agent evolution observatory from the header", async () => {
    const { wrapper } = await setup();
    await wrapper.get('[data-test="header-experience-evolution"]').trigger("click");
    await flushPromises();
    const dialog = portal("experience-evolution-dialog");
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain("智能体进化");
    expect(dialog?.textContent).toContain("Experience Skill v4");
    expect(dialog?.textContent).toContain("EXP-XAJ-0018");
    wrapper.unmount();
  });

  it("shows a glass dialog when the run is queued behind occupied seats", async () => {
    vi.mocked(api.startRun).mockResolvedValueOnce({
      status: "queued",
      worker_active: false,
      queue_position: 2,
      worker_slots_used: 5,
      worker_slots_max: 5,
    } as Awaited<ReturnType<typeof api.startRun>>);
    vi.mocked(api.getRun).mockResolvedValue({
      status: "queued",
      worker_active: false,
      queue_position: 2,
      worker_slots_used: 5,
      worker_slots_max: 5,
    } as Awaited<ReturnType<typeof api.getRun>>);
    const { wrapper } = await setup();
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    const notice = portal("run-notice");
    expect(notice).not.toBeNull();
    expect(notice?.textContent).toContain("已加入排队");
    expect(notice?.textContent).toContain("第 2 位");
    portal("run-notice")
      ?.querySelector<HTMLButtonElement>('[data-test="run-notice-ack"]')
      ?.click();
    await flushPromises();
    expect(portal("run-notice")).toBeNull();
    expect(wrapper.find(".start-button").text()).toContain("排队等待计算席位");
    wrapper.unmount();
  });

  it("shows a glass dialog when compute seats are full", async () => {
    vi.mocked(api.startRun).mockRejectedValueOnce(
      new Error(
        'API 409: {"detail":"计算席位已满（最多同时运行 5 个任务），请稍后再试"}',
      ),
    );
    const { wrapper } = await setup();
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    const notice = portal("run-notice");
    expect(notice).not.toBeNull();
    expect(notice?.textContent).toContain("暂时无法开始");
    expect(notice?.textContent).toContain("最多同时运行 5 个任务");
    wrapper.unmount();
  });

  it("keeps basin selection with preparation and keeps runtime configuration separate", async () => {
    const { wrapper } = await setup();
    const children = [...wrapper.find(".observatory-grid").element.children].flatMap((node) => {
      if ((node as HTMLElement).classList?.contains("mobile-deck")) {
        return [...node.children];
      }
      return [node];
    }) as HTMLElement[];
    expect(children[0].className).toContain("main-stage");
    expect(children[1].className).toContain("task-pane");
    expect(children[2].className).toContain("journal-pane");
    expect(wrapper.find(".main-stage [data-test=\"basin-selector\"]").exists()).toBe(true);
    expect(wrapper.find(".task-pane [data-test=\"basin-selector\"]").exists()).toBe(false);
    expect(wrapper.find(".task-pane h2").text()).toBe("本次运行");
    expect(wrapper.find(".journal-pane h2").text()).toBe("完整执行记录");
    expect(wrapper.find(".record-count").exists()).toBe(false);
    expect(wrapper.find(".water-scene").exists()).toBe(false);
    expect(wrapper.find(".stage-track").exists()).toBe(false);
    expect(wrapper.find(".hero-copy").exists()).toBe(false);
    wrapper.unmount();
  });

  it("lists Leaf River and keeps the selected basin", async () => {
    const { wrapper, store } = await setup();
    const selector = wrapper.find('[data-test="basin-selector"]');
    expect(selector.text()).toContain("腰古");
    await selector.trigger("click");
    await flushPromises();
    const option = document.body.querySelector(
      '[data-value="usgs_02472000"]',
    ) as HTMLElement | null;
    expect(option).not.toBeNull();
    option?.click();
    await flushPromises();
    expect(store.draft.basin_id).toBe("usgs_02472000");
    expect(wrapper.find('.source-note').exists()).toBe(false);
    expect(wrapper.find('[data-test="demo-preset"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("preserves valid demo dates when a ready plan is bound", async () => {
    vi.mocked(api.health).mockResolvedValueOnce({
      status: "ok",
      mode: "real",
      model_preparation: true,
      basin_catalog: true,
    });
    const { wrapper, store } = await setup();
    store.draft.start_date = "2000-04-01";
    store.draft.end_date = "2000-08-31";
    wrapper.findComponent(ModelPreparation).vm.$emit("selected", {
      plan_id: "plan-ready",
      basin_id: "yaogu",
      status: "ready",
      stages: [],
      suggested_start: "1990-03-14",
      suggested_end: "1990-03-28",
      data_start: "1990-01-01",
      data_end: "2005-12-31",
    });
    await flushPromises();
    expect(store.draft.model_plan_id).toBe("plan-ready");
    expect(store.draft.start_date).toBe("2000-04-01");
    expect(store.draft.end_date).toBe("2000-08-31");
    expect(wrapper.find('[data-test="start-date"]').attributes("min")).toBe(
      "1990-01-01",
    );
    expect(wrapper.find('[data-test="end-date"]').attributes("max")).toBe(
      "2005-12-31",
    );
    wrapper.unmount();
  });

  it("repairs dates that fall outside the bound plan range", async () => {
    vi.mocked(api.health).mockResolvedValueOnce({
      status: "ok",
      mode: "real",
      model_preparation: true,
      basin_catalog: true,
    });
    const { wrapper, store } = await setup();
    const plan = {
      plan_id: "plan-ready",
      basin_id: "yaogu",
      status: "ready",
      stages: [] as [],
      suggested_start: "1990-03-14",
      suggested_end: "1990-03-28",
      data_start: "1990-01-01",
      data_end: "2005-12-31",
    };
    store.draft.start_date = "1989-01-01";
    store.draft.end_date = "1989-06-01";
    wrapper.findComponent(ModelPreparation).vm.$emit("selected", plan);
    await flushPromises();
    expect(store.draft.start_date).toBe("1990-03-14");
    expect(store.draft.end_date).toBe("1990-03-28");
    store.draft.start_date = "2006-01-01";
    store.draft.end_date = "2006-06-01";
    wrapper.findComponent(ModelPreparation).vm.$emit("selected", plan);
    await flushPromises();
    expect(store.draft.start_date).toBe("1990-03-14");
    expect(store.draft.end_date).toBe("1990-03-28");
    wrapper.unmount();
  });

  it("uses the verified demo defaults without exposing a reload control", async () => {
    const { wrapper, store } = await setup();
    expect(store.draft).toMatchObject(DEMO_PRESET);
    expect(
      (wrapper.find('[data-test="start-date"]').element as HTMLInputElement)
        .value,
    ).toBe("2000-04-01");
    expect(
      (wrapper.find('[data-test="end-date"]').element as HTMLInputElement)
        .value,
    ).toBe("2000-08-31");
    expect(wrapper.find('[data-test="demo-preset"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("submits development and final-test windows with backend budget limits", async () => {
    const { wrapper } = await setup();
    expect(wrapper.find('[data-test="campaign-budget"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="campaign-budget"]').element.parentElement?.textContent).toContain("本次率定最多运行多少次模型");
    await wrapper.find('[data-test="runtime-settings"]').trigger("click");
    const development = wrapper.find('[data-test="development-days"]');
    const finalTest = wrapper.find('[data-test="final-test-days"]');
    expect(development.exists()).toBe(true);
    expect(finalTest.exists()).toBe(true);
    expect(development.attributes("min")).toBe("3");
    expect(development.attributes("max")).toBe("90");
    expect(finalTest.attributes("min")).toBe("3");
    expect(finalTest.attributes("max")).toBe("90");
    expect(
      wrapper
        .find('input[v-model="demo.draft.max_agent_decision_rounds"]')
        .exists(),
    ).toBe(false);
    expect(wrapper.find('[data-test="campaign-budget"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="campaign-mode"]').text()).toContain(
      "连通验证",
    );
    await development.setValue(21);
    await finalTest.setValue(14);
    await wrapper.find('[data-test="campaign-budget"]').setValue(600);
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(api.createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        validation_days: 21,
        final_test_days: 14,
        max_agent_decision_rounds: 30,
        max_optimization_cycles: 4,
        campaign_mode: "smoke",
        campaign_max_model_evaluations: 600,
      }),
    );
    wrapper.unmount();
  });

  it("shows one final comparison chart, research audit, and removes the redundant forecast-record chart", async () => {
    const { wrapper, store, router } = await setup();
    store.taskId = "test-task";
    store.run = {
      status: "completed",
      // Experience evolution can keep the worker occupied after the
      // hydrologic task itself has reached its terminal result.
      worker_active: true,
      phase: "E",
      needs_follow_up: false,
    } as typeof store.run;
    store.results = {
      task_id: "test-task",
      phase: "E",
      scheme: {
        scheme_id: "s",
        status: "frozen",
        content_hash: "h",
        model_id: "xaj",
        provenance: {},
        parameters: { K: 0.75, SM: 20 },
        base_parameters: { K: 0.75, SM: 20 },
        parameter_delta: {},
        adopted_parameter_delta: {},
        candidate_scheme_id: "candidate-1",
        candidate_parameters: { K: 0.5, SM: 30 },
        candidate_parameter_delta: { K: -0.25, SM: 10 },
      },
      forecasts: [
        {
          forecast_id: "f",
          scheme_id: "s",
          issue_time: "2020-01-01",
          lead_values: { 1: 10 },
          unit: "m3/s",
        },
      ],
      metrics: {},
      gate: {
        status: "KEEP",
        reason_codes: ["insufficient_absolute_skill"],
        metrics: { base_primary: -300, candidate_primary: -220 },
      },
      diagnosis: {
        hypothesis: "MODEL",
        phenomenon: "洪峰低估",
        hypotheses_json: JSON.stringify([
          { id: "MODEL", strength: 0.8, phenomenon: "洪峰低估" },
        ]),
      },
      optimize: {
        strategy_id: "xaj-peak-bias-v1",
        param_groups: "runoff,routing",
        objective: "composite",
        metrics: { objective_value: 0.12 },
      },
      test_hydrograph: {
        kind: "independent_test",
        title: "独立检验",
        calibrated: false,
        gate_status: "KEEP",
        warmup_days: 0,
        evaluated_days: 2,
        series: [
          {
            time: "2020-01-01",
            observed_m3s: 10,
            baseline_m3s: 9,
            frozen_m3s: 9,
            window: "test",
            is_warmup: false,
          },
          {
            time: "2020-01-02",
            observed_m3s: 12,
            baseline_m3s: 11,
            frozen_m3s: 11,
            window: "test",
            is_warmup: false,
          },
        ],
        baseline_metrics: { nse: 0.4 },
        frozen_metrics: { nse: 0.4 },
      },
      report_artifacts: ["report.md"],
      costs: {},
    };
    await flushPromises();
    expect(wrapper.findAll('[data-test="hydrograph"]')).toHaveLength(1);
    expect(
      wrapper.find('[data-test="scheme-metric-comparison"]').exists(),
    ).toBe(true);
    expect(wrapper.find('[data-test="research-evidence-panel"]').exists()).toBe(
      true,
    );
    expect(wrapper.text()).toContain("最终方案是否贴住观测过程线");
    expect(wrapper.text()).toContain("观测 / 基准 / 最终方案");
    expect(wrapper.text()).not.toContain("预报记录");
    expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="forecast-surface"]').exists()).toBe(true);
    expect(wrapper.find(".observatory").classes()).toContain("is-results");
    expect(wrapper.find('[data-test="header-new-task"]').text()).toBe(
      "新建任务",
    );
    expect(wrapper.find('[data-test="header-case-picker"]').exists()).toBe(
      true,
    );
    expect(wrapper.find('[data-test="header-delete-case"]').exists()).toBe(
      true,
    );
    expect(
      wrapper.find('[data-test="header-delete-case"]').classes(),
    ).toContain("manage-button");
    expect(wrapper.find('[data-test="param-tuning"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="hydrologist-tune"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("新安江参数如何被调整");
    expect(wrapper.text()).toContain(
      "优化器提出的候选参数（变化 2 项，未必采用）",
    );
    expect(wrapper.text()).toContain("最终采用参数（正式变化 0 项）");
    expect(wrapper.text()).toContain("并非优化器没有工作");
    expect(wrapper.find('a[href*="/report/"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("结果与报告");
    expect(router.currentRoute.value.path).toBe("/");
    wrapper.unmount();
  });

  it("supports selecting and deleting multiple historical cases in one operation", async () => {
    const { wrapper, store } = await setup();
    store.caseLibrary = [
      {
        task_id: "case-1",
        basin_id: "yaogu",
        model_id: "xaj",
        phase: "E",
        status: "completed",
        paused: false,
        current_scheme_id: "s1",
        agent_rounds_used: 4,
        optimization_cycles_used: 1,
        start_date: "2020-01-01",
      },
      {
        task_id: "case-2",
        basin_id: "yaogu",
        model_id: "xaj",
        phase: "E",
        status: "completed",
        paused: false,
        current_scheme_id: "s2",
        agent_rounds_used: 5,
        optimization_cycles_used: 2,
        start_date: "2020-02-01",
      },
    ];
    await flushPromises();

    await wrapper.find('[data-test="header-case-library"]').trigger("click");
    await flushPromises();
    const library = portal("case-library");
    expect(library).not.toBeNull();
    library
      ?.querySelector<HTMLButtonElement>(".text-button")
      ?.click();
    await flushPromises();
    await flushPromises();
    const manager = portal("case-manager");
    expect(manager).not.toBeNull();
    expect(manager?.parentElement).toBe(document.body);
    const checkboxes = [
      ...(manager?.querySelectorAll('input[type="checkbox"]') || []),
    ].map((el) => new DOMWrapper(el as HTMLInputElement));
    expect(checkboxes).toHaveLength(2);
    await checkboxes[0].setValue(true);
    await checkboxes[1].setValue(true);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await new DOMWrapper(
      manager!.querySelector('[data-test="delete-selected-cases"]')!,
    ).trigger("click");
    await flushPromises();
    expect(api.deleteTask).toHaveBeenCalledWith("case-1");
    expect(api.deleteTask).toHaveBeenCalledWith("case-2");
    expect(portal("case-manager")).toBeNull();
    confirm.mockRestore();
    wrapper.unmount();
  });

  it("shows the results surface even before final comparison data arrive", async () => {
    const { wrapper, store } = await setup();
    store.taskId = "test-task";
    store.run = {
      status: "completed",
      worker_active: false,
      phase: "E",
      needs_follow_up: false,
    } as typeof store.run;
    store.results = {
      task_id: "test-task",
      phase: "E",
      scheme: null,
      forecasts: [],
      metrics: {},
      gate: { status: "KEEP" },
      report_artifacts: [],
      costs: {},
    };
    await flushPromises();
    expect(wrapper.find('[data-test="live-workflow"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="forecast-surface"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="research-evidence-panel"]').exists()).toBe(
      true,
    );
    expect(wrapper.text()).toContain("最终方案对比");
    expect(wrapper.text()).toContain("指标先对照");
    expect(wrapper.find(".observatory").classes()).toContain("is-results");
    expect(wrapper.find('[data-test="header-new-task"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("restores existing sessions without restarting compute", async () => {
    sessionStorage.setItem(
      "hydro-demo-session",
      JSON.stringify({
        taskId: "existing",
        mode: "live",
        draft: {
          basin_id: "old",
          model_id: "xaj",
          start_date: "2020-01-01",
          end_date: "2020-01-03",
          forcing_mode: "R",
          base_scheme_id: "base",
          allow_optimization: true,
          max_agent_decision_rounds: 20,
          max_optimization_cycles: 4,
        },
        startedAt: null,
      }),
    );
    const { wrapper, store } = await setup();
    expect(api.getTask).toHaveBeenCalledWith("existing");
    expect(store.draft.basin_id).toBe("basin-restored");
    expect(store.draft.validation_days).toBe(30);
    expect(store.draft.final_test_days).toBe(30);
    expect(store.draft.campaign_mode).toBe("smoke");
    expect(store.draft.campaign_max_model_evaluations).toBe(800);
    expect(store.draft.max_agent_decision_rounds).toBe(20);
    expect(api.startRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps a dedicated agent-calibration section after rollback", async () => {
    vi.mocked(api.getResearch).mockResolvedValueOnce({
      task_id: "test-task",
      protocol: {},
      latest_experiment_plan: null,
      trials: [
        {
          trial_id: "trial-1",
          plan_id: "plan-1",
          experiment_signature: "sig",
          strategy_id: "xaj-broadened-refine-v1",
          model_evaluations: 494,
          development_gate: "ROLLBACK",
          adoption_status: "REJECT",
          qualification_status: "UNQUALIFIED",
          metric_deltas: {},
          parameter_delta: { K: -0.12, SM: 6.5 },
          baseline_nse: -6.315,
          candidate_nse: 0.819,
          gate_reasons: ["lead_1_guardrail"],
          evidence_refs: [],
          hypothesis_outcome: "refuted",
          reason_codes: [],
        },
      ],
      final_test_evidence: null,
      final_test_audit: { consumed: true, read_only: true, single_use: true },
      contracts: {
        rolling_continuous_separated: true,
        final_test_used_for_selection: false,
        trial_ledger_source: "persisted_evidence",
        objective_alias: "composite->kge",
      },
    } as never);
    const { wrapper, store } = await setup();
    store.taskId = "test-task";
    store.run = {
      status: "completed",
      worker_active: false,
      phase: "E",
      needs_follow_up: false,
    } as typeof store.run;
    store.results = {
      task_id: "test-task",
      phase: "E",
      scheme: {
        scheme_id: "s",
        status: "frozen",
        content_hash: "h",
        model_id: "xaj",
        provenance: {},
      },
      forecasts: [],
      metrics: {},
      gate: { status: "ROLLBACK" },
      calibration_hydrograph: {
        kind: "calibration",
        title: "率定",
        calibrated: false,
        gate_status: "ROLLBACK",
        warmup_days: 1,
        evaluated_days: 9,
        series: [
          {
            time: "1990-03-20",
            observed_m3s: 10,
            baseline_m3s: 4,
            candidate_m3s: 9,
            window: "calibration",
            is_warmup: false,
          },
        ],
      },
      test_hydrograph: {
        kind: "independent_test",
        title: "检验",
        calibrated: false,
        gate_status: "ROLLBACK",
        warmup_days: 0,
        evaluated_days: 3,
        series: [
          {
            time: "1990-03-26",
            observed_m3s: 12,
            baseline_m3s: 8,
            frozen_m3s: 8,
            window: "test",
            is_warmup: false,
          },
        ],
      },
      report_artifacts: ["report.md"],
      costs: {},
    };
    await flushPromises();
    expect(wrapper.find('[data-test="agent-calibration-panel"]').exists()).toBe(
      true,
    );
    expect(wrapper.text()).toContain("智能体调参");
    expect(wrapper.text()).toContain("xaj-broadened-refine-v1");
    expect(wrapper.text()).toContain("第 1 日预见期 NSE 下降超过允许值");
    expect(wrapper.findAll('[data-test="hydrograph"]')).toHaveLength(2);
    wrapper.unmount();
  });
});
