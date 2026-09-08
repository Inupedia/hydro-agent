from .adapter import RuntimeAdapter
from .contracts import ExecutionCapability


class RuntimeRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {}

    def register(self, adapter: RuntimeAdapter) -> None:
        if adapter.model_id in self._adapters:
            raise ValueError(f"model {adapter.model_id} already registered")
        self._adapters[adapter.model_id] = adapter

    def get(self, model_id: str, capability: ExecutionCapability) -> RuntimeAdapter:
        if model_id not in self._adapters:
            raise ValueError(f"unknown model {model_id}")
        adapter = self._adapters[model_id]
        if capability not in adapter.capabilities:
            raise ValueError(f"model {model_id} does not support {capability}")
        return adapter
