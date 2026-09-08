"""Explicit, paid connectivity check: python -m hydro_agent.llm.smoke."""

import json

from .client import LLMError, SiliconFlowClient
from .settings import LLMSettings


def main():
    try:
        settings = LLMSettings.from_env()
        result = SiliconFlowClient(settings).complete(
            [{"role": "user", "content": "Reply with exactly OK."}], max_tokens=1024
        )
    except (LLMError, ValueError) as exc:
        # Never serialize configuration validation inputs.
        message = str(exc) if isinstance(exc, LLMError) else "invalid local LLM configuration"
        print(json.dumps({"status": "failed", "error": message}))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "status": "succeeded",
                "model": result.model,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "wall_time_seconds": round(result.wall_time_seconds, 3),
                "nonempty_response": bool(result.content.strip()),
            }
        )
    )


if __name__ == "__main__":
    main()
