"""Domain skill cards for Hydro-Agent decision support.

Skills are not free-form prompts: they declare when to use a method, what evidence
is required, what action/strategy they recommend, and when to stop.
"""

from __future__ import annotations

from hydro_agent.execution.contracts import FrozenModel


class SkillCard(FrozenModel):
    skill_id: str
    title_zh: str
    purpose_zh: str
    when_to_use_zh: tuple[str, ...]
    required_evidence_zh: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    recommended_strategies: tuple[str, ...] = ()
    stop_conditions_zh: tuple[str, ...] = ()
    counterexamples_zh: tuple[str, ...] = ()


SKILLS: tuple[SkillCard, ...] = (
    SkillCard(
        skill_id="data-check",
        title_zh="资料核查",
        purpose_zh="确认强迫与观测是否足以支撑预报/率定，而不是默认模型问题。",
        when_to_use_zh=("任务刚开始", "预报失败", "观测样本不足"),
        required_evidence_zh=("流域与方案存在", "snapshot 或源数据可物化"),
        recommended_actions=("A01_CHECK_DATA", "A03_VALIDATE_SCHEME"),
        stop_conditions_zh=("资料不可用且无法修复",),
        counterexamples_zh=("已有完整预报证据时不要反复只做资料检查",),
    ),
    SkillCard(
        skill_id="forecast-diagnose",
        title_zh="预报诊断",
        purpose_zh="根据误差形态提出受约束的原因假说，并指定下一实验。",
        when_to_use_zh=("已有基础预报", "Gate 拒绝后需要解释", "准备再次优化前"),
        required_evidence_zh=("lead 1/2/3 预报", "同期观测", "偏差/洪峰比"),
        recommended_actions=("A06_DIAGNOSE", "A07_OPTIMIZE", "A10_FREEZE"),
        recommended_strategies=("xaj-hydrologist-manual-v1", "xaj-bounded-v1", "xaj-peak-bias-v1", "xaj-local-refine-v1"),
        stop_conditions_zh=("观测不足以诊断", "预算耗尽"),
        counterexamples_zh=("没有预报证据时不要空诊断", "不要把单次 forcing 分歧直接当成模型缺陷"),
    ),
    SkillCard(
        skill_id="bounded-adapt",
        title_zh="有限适配与验证",
        purpose_zh="只允许受约束策略搜索，并在独立验证窗上 Gate。",
        when_to_use_zh=("诊断指向 MODEL", "仍有优化预算", "已有候选或准备产生候选"),
        required_evidence_zh=("策略 id", "率定 snapshot", "独立验证窗"),
        recommended_actions=("A07_OPTIMIZE", "A08_GATE", "A09_RESOLVE"),
        recommended_strategies=("xaj-hydrologist-manual-v1", "xaj-bounded-v1", "xaj-peak-bias-v1", "xaj-local-refine-v1"),
        stop_conditions_zh=("Gate 连续失败", "优化预算用尽", "改善不足且无新假说"),
        counterexamples_zh=("不要让 LLM 直接发明连续参数向量",),
    ),
)


class SkillRegistry:
    def __init__(self, skills: tuple[SkillCard, ...] = SKILLS):
        self._skills = {s.skill_id: s for s in skills}

    def list(self) -> tuple[SkillCard, ...]:
        return tuple(self._skills[k] for k in sorted(self._skills))

    def get(self, skill_id: str) -> SkillCard:
        return self._skills[skill_id]

    def summaries_zh(self) -> tuple[str, ...]:
        return tuple(f"{s.skill_id}:{s.title_zh}" for s in self.list())

    def cards_for_prompt(self) -> list[dict]:
        return [s.model_dump(mode="json") for s in self.list()]
