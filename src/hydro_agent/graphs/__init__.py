"""LangGraph orchestration for forecast research and hydrologist workflows."""

__all__ = [
    "build_forecast_graph",
    "build_hydrologist_tune_graph",
    "run_forecast_until_terminal",
]


def __getattr__(name: str):
    if name in {"build_forecast_graph", "run_forecast_until_terminal"}:
        from hydro_agent.graphs.forecast import build_forecast_graph, run_forecast_until_terminal

        return {
            "build_forecast_graph": build_forecast_graph,
            "run_forecast_until_terminal": run_forecast_until_terminal,
        }[name]
    if name == "build_hydrologist_tune_graph":
        from hydro_agent.graphs.hydrologist import build_hydrologist_tune_graph

        return build_hydrologist_tune_graph
    raise AttributeError(name)
