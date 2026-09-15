# ConvergencePolicy

停止搜索必须来自预注册的 Campaign 证据，例如稳定 plateau、重启检查、预算安全上限或其他显式 stop condition。

单次 NSE/KGE 达到某个值、某个 Skill 认为“已经不错”、或一次 Gate ACCEPT 都不等于科学收敛。`campaign.stop_reason` 是运行时停止事实的统一入口。