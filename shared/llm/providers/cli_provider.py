"""
Claude CLI Provider — uses the local `claude` CLI (Claude Code) for queries.
No API key needed — uses the active session from Claude Code (Plan Max, etc).

Two modes:
  1. Direct subprocess (when running on the host)
  2. Proxy HTTP (when running inside Docker — calls claude_proxy.py on the host)
"""

import os
import asyncio
import shutil
import json
import urllib.request
import urllib.error
from typing import Optional, List, AsyncIterator, Union
from ..base import LLMProvider, LLMResponse, LLMOptions, ModelType, ANTHROPIC_MODEL_IDS


MODEL_MAP = ANTHROPIC_MODEL_IDS

# host.docker.internal resolves to the host machine from inside Docker
PROXY_HOST = os.getenv("CLAUDE_PROXY_HOST", "host.docker.internal")
PROXY_PORT = int(os.getenv("CLAUDE_PROXY_PORT", "8099"))


class ClaudeCliProvider(LLMProvider):
    """
    Calls the `claude` CLI, either directly or via the host proxy.
    Auto-detects mode based on whether the CLI session works locally.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.cli_path = config.get("cli_path") or shutil.which("claude") or "claude"
        self.timeout = int(config.get("timeout", 300))
        self._use_proxy: Optional[bool] = None  # resolved at initialize()

    async def initialize(self) -> None:
        # Try direct CLI first; fall back to proxy
        if await self._cli_works_locally():
            self._use_proxy = False
            print("🖥️  Claude CLI: direct subprocess mode")
        elif await self._proxy_reachable():
            self._use_proxy = True
            print(f"🌐 Claude CLI: proxy mode ({PROXY_HOST}:{PROXY_PORT})")
        else:
            raise RuntimeError(
                "Claude CLI not available locally and proxy not reachable. "
                f"Run: python3 scripts/claude_proxy.py  (host port {PROXY_PORT})"
            )
        self._initialized = True

    async def _cli_works_locally(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_path, "--print", "--model", MODEL_MAP[ModelType.HAIKU],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=b"Say OK"),
                timeout=15,
            )
            return proc.returncode == 0
        except Exception:
            return False

    async def _proxy_reachable(self) -> bool:
        try:
            url = f"http://{PROXY_HOST}:{PROXY_PORT}/health"
            req = urllib.request.urlopen(url, timeout=5)
            return req.status == 200
        except Exception:
            return False

    async def query(
        self, prompt: str, options: Optional[LLMOptions] = None
    ) -> Union[LLMResponse, AsyncIterator[str]]:
        options = options or LLMOptions()
        model_id = MODEL_MAP.get(options.model, MODEL_MAP[ModelType.SONNET])

        if self._use_proxy:
            content = await self._query_via_proxy(prompt, model_id)
        else:
            content = await self._query_via_cli(prompt, model_id, options.system_prompt)

        if options.stream:
            async def _stream():
                chunk_size = 200
                for i in range(0, len(content), chunk_size):
                    yield content[i:i + chunk_size]
                    await asyncio.sleep(0)
            return _stream()

        return LLMResponse(
            content=content,
            model=model_id,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop",
            metadata={"provider": "claude_cli", "via_proxy": self._use_proxy},
        )

    async def _query_via_cli(self, prompt: str, model_id: str, system_prompt: Optional[str]) -> str:
        cmd = [self.cli_path, "--print", "--model", model_id]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"claude CLI timed out after {self.timeout}s")
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI error (exit {proc.returncode}): {stderr.decode().strip()}")
        return stdout.decode().strip()

    async def _query_via_proxy(self, prompt: str, model_id: str) -> str:
        url = f"http://{PROXY_HOST}:{PROXY_PORT}/query"
        payload = json.dumps({"prompt": prompt, "model": model_id}).encode()
        loop = asyncio.get_event_loop()
        try:
            def _call():
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            data = await loop.run_in_executor(None, _call)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"Proxy error {e.code}: {body}")
        except Exception as e:
            raise RuntimeError(f"Proxy unreachable: {e}")
        if "error" in data:
            raise RuntimeError(f"Proxy returned error: {data['error']}")
        return data.get("content", "")

    async def health_check(self) -> bool:
        if self._use_proxy:
            return await self._proxy_reachable()
        return await self._cli_works_locally()

    async def close(self) -> None:
        self._initialized = False

    def supported_models(self) -> List[ModelType]:
        return [ModelType.OPUS, ModelType.SONNET, ModelType.HAIKU]

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: ModelType) -> float:
        return 0.0  # Plan Max — no per-token cost
