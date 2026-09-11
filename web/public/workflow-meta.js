/* Generated from workflow/hydro-agent.v*.json. Do not edit. */
window.HYDRO_WORKFLOW_META = {
  "workflow_id": "hydro-agent-calibration",
  "version": "1.0.0",
  "hash": "sha256:a0aa0ee0be8cf8c095e5a15f341fed064dcbc7cad44e54d5494a21d91362306d",
  "html_name": "hydro-agent.v1.workflow.html",
  "diagrams_by_version": {
    "1.0.0": "hydro-agent.v1.workflow.html"
  },
  "display_stages": [
    {
      "id": "data",
      "label": "准备资料"
    },
    {
      "id": "forecast",
      "label": "计算预测"
    },
    {
      "id": "gate",
      "label": "检查与改进"
    },
    {
      "id": "report",
      "label": "形成结果"
    }
  ],
  "step_order": [
    "A01_CHECK_DATA",
    "A03_VALIDATE_SCHEME",
    "A05_FORECAST",
    "A06_DIAGNOSE",
    "A07_OPTIMIZE",
    "A08_GATE",
    "A09_RESOLVE",
    "A10_FREEZE",
    "A11_REPLAY",
    "A12_EVALUATE_REPORT"
  ],
  "actions": {
    "M01_CHECK_MATERIALS": {
      "kind": "modeling",
      "enabled": true,
      "label_zh": "检查建模资料",
      "title_running_zh": "检查建模资料",
      "title_done_zh": "检查了建模资料",
      "explain_zh": "确认 DEM、站点与日资料是否齐全。",
      "display_stage": "data",
      "display_node": "materials",
      "display_node_by_status": {}
    },
    "M02_DELINEATE": {
      "kind": "modeling",
      "enabled": true,
      "label_zh": "提取流域与计算单元",
      "title_running_zh": "提取流域与计算单元",
      "title_done_zh": "提取了流域边界",
      "explain_zh": "由出口与 DEM 提取边界和计算单元。",
      "display_stage": "data",
      "display_node": "delineate",
      "display_node_by_status": {}
    },
    "M03_REVIEW_BOUNDARY": {
      "kind": "modeling",
      "enabled": true,
      "label_zh": "复核出口与边界",
      "title_running_zh": "复核出口与边界",
      "title_done_zh": "确认了流域边界",
      "explain_zh": "查看地图后确认当前边界，修改上游必须另建版本。",
      "display_stage": "data",
      "display_node": "boundary",
      "display_node_by_status": {}
    },
    "M04_BUILD_INPUTS": {
      "kind": "modeling",
      "enabled": true,
      "label_zh": "构建面雨量与模型输入",
      "title_running_zh": "构建面雨量与模型输入",
      "title_done_zh": "构建了模型输入",
      "explain_zh": "按空间权重构建面雨量、参数与时间轴。",
      "display_stage": "data",
      "display_node": "inputs",
      "display_node_by_status": {}
    },
    "M05_VALIDATE_PLAN": {
      "kind": "modeling",
      "enabled": true,
      "label_zh": "校验完整模型方案",
      "title_running_zh": "校验完整模型方案",
      "title_done_zh": "校验了完整方案",
      "explain_zh": "文件校验通过后固定方案版本。",
      "display_stage": "data",
      "display_node": "plan",
      "display_node_by_status": {}
    },
    "A01_CHECK_DATA": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "资料检查",
      "title_running_zh": "正在检查资料",
      "title_done_zh": "检查了资料",
      "explain_zh": "确认本次计算需要的气象与流量资料是否齐全。",
      "display_stage": "data",
      "display_node": "check_data",
      "display_node_by_status": {}
    },
    "A02_REPAIR_DATA": {
      "kind": "runtime",
      "enabled": false,
      "label_zh": "资料修复",
      "title_running_zh": "正在修复资料",
      "title_done_zh": "修复了资料",
      "explain_zh": "在资料检查失败后尝试修复；当前版本尚未启用。",
      "display_stage": "data",
      "display_node": "check_data",
      "display_node_by_status": {}
    },
    "A03_VALIDATE_SCHEME": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "方案校验",
      "title_running_zh": "正在校验方案",
      "title_done_zh": "校验了方案",
      "explain_zh": "确认基础计算方案可以投入运行。",
      "display_stage": "data",
      "display_node": "validate_scheme",
      "display_node_by_status": {}
    },
    "A04_REBUILD_STATE": {
      "kind": "runtime",
      "enabled": false,
      "label_zh": "重建状态",
      "title_running_zh": "正在重建状态",
      "title_done_zh": "重建了状态",
      "explain_zh": "在状态假设成立时重建暖机状态；当前版本尚未启用。",
      "display_stage": "forecast",
      "display_node": "forecast",
      "display_node_by_status": {}
    },
    "A05_FORECAST": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "基础预报",
      "title_running_zh": "正在计算预测",
      "title_done_zh": "完成了流量预测",
      "explain_zh": "用当前方案计算未来几天的流量。",
      "display_stage": "forecast",
      "display_node": "forecast",
      "display_node_by_status": {}
    },
    "A06_DIAGNOSE": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "预报诊断",
      "title_running_zh": "正在诊断预报误差",
      "title_done_zh": "诊断了预报误差",
      "explain_zh": "对照观测，判断误差更可能来自哪里，以及是否值得率定。",
      "display_stage": "gate",
      "display_node": "diagnose",
      "display_node_by_status": {}
    },
    "A07_OPTIMIZE": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "有限调参",
      "title_running_zh": "正在尝试调整参数",
      "title_done_zh": "尝试调整了参数",
      "explain_zh": "在有限范围内尝试更合适的参数，不直接搜索连续向量。",
      "display_stage": "gate",
      "display_node": "optimize",
      "display_node_by_status": {}
    },
    "A08_GATE": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "把关 Gate",
      "title_running_zh": "正在检查是否达到要求",
      "title_done_zh": "检查了是否达到要求",
      "explain_zh": "比较候选方案与原方案，看是否值得更换。",
      "display_stage": "gate",
      "display_node": "gate",
      "display_node_by_status": {}
    },
    "A09_RESOLVE": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "落实 Gate 结论",
      "title_running_zh": "正在落实检查结论",
      "title_done_zh": "落实了检查结论",
      "explain_zh": "根据检查结果决定采用、保留或回退。",
      "display_stage": "gate",
      "display_node": "keep",
      "display_node_by_status": {
        "ACCEPT": "accept",
        "KEEP": "keep",
        "ROLLBACK": "rollback",
        "blocked": "blocked",
        "failed": "blocked"
      }
    },
    "A10_FREEZE": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "冻结方案",
      "title_running_zh": "正在确定采用方案",
      "title_done_zh": "确定了采用方案",
      "explain_zh": "把当前采用方案锁定，供后续回放与报告使用。",
      "display_stage": "report",
      "display_node": "freeze",
      "display_node_by_status": {}
    },
    "A11_REPLAY": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "历史回放",
      "title_running_zh": "正在做历史资料回放",
      "title_done_zh": "完成了历史资料回放",
      "explain_zh": "用历史资料把锁定方案再跑一遍，方便对照。",
      "display_stage": "report",
      "display_node": "replay",
      "display_node_by_status": {}
    },
    "A12_EVALUATE_REPORT": {
      "kind": "runtime",
      "enabled": true,
      "label_zh": "评估报告",
      "title_running_zh": "正在整理结果与报告",
      "title_done_zh": "整理了结果与报告",
      "explain_zh": "汇总指标、说明与可下载产物。",
      "display_stage": "report",
      "display_node": "report",
      "display_node_by_status": {}
    }
  }
};
