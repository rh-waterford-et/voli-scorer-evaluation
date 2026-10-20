"""Run parameters and stream_metrics.py command construction.

The dashboard always invokes scripts/stream_metrics.py once per selected
profile, using single-profile mode (--profile NAME). That mode accepts any
profile name -- including profiles discovered from the live EPP ConfigMap
that are not in the script's built-in PROFILE_SCORERS map -- and repeated
--run flags still produce a suite-shaped JSON document when there is more
than one load setting.
"""

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ENDPOINTS = ("/v1/chat/completions", "/v1/audio/speech")


class LoadSetting(BaseModel):
    """One load level: N total requests with at most C in flight."""

    iterations: int = Field(default=10, ge=1, le=100_000)
    concurrency: int = Field(default=1, ge=1, le=1_000)


class RunParams(BaseModel):
    """Benchmark parameters; mirrors the stream_metrics.py flags we expose."""

    endpoint: Literal["/v1/chat/completions", "/v1/audio/speech"] = "/v1/audio/speech"
    model: str = Field(default="qwen3-tts", min_length=1)
    url: str = Field(default="http://10.6.62.51:31670", min_length=1)
    # Required: the caller picks profiles explicitly. "default" is a valid
    # choice (it sends no EPP-Profile header), but it is never implied.
    profiles: list[str] = Field(min_length=1)
    runs: list[LoadSetting] = Field(default_factory=lambda: [LoadSetting()], min_length=1)

    prompt: Optional[str] = None
    prompts_text: Optional[str] = None  # multi-line; each nonempty line is one prompt
    modalities: str = "text,audio"  # chat-completions output only
    voice: Optional[str] = None
    audio_format: Optional[str] = None
    tokenizer: Optional[str] = None  # required for /v1/chat/completions
    api_key: Optional[str] = None

    session_length: int = Field(default=0, ge=0)  # 0 disables; >= 2 groups sessions
    session_header: str = "x-session-token"

    epp_scores: bool = False
    no_backend_lookup: bool = False
    no_usage: bool = False

    namespace: str = "vllm-omni-validation"
    gateway_name: str = "inference-gateway"
    gateway_container: str = "istio-proxy"
    epp_deployment: str = "endpoint-picker-epp"
    epp_container: str = "epp"
    epp_configmap: Optional[str] = None
    epp_config_key: Optional[str] = None
    gateway_wait: float = Field(default=10, ge=0)
    epp_wait: float = Field(default=5, ge=0)
    timeout: float = Field(default=600, gt=0)

    @model_validator(mode="after")
    def _check(self):
        if self.endpoint == "/v1/chat/completions" and not (self.tokenizer or "").strip():
            raise ValueError("tokenizer is required for /v1/chat/completions runs")
        if self.session_length == 1:
            raise ValueError("session_length must be 0 (disabled) or at least 2")
        parts = [part.strip() for part in self.modalities.split(",")]
        if self.endpoint == "/v1/chat/completions":
            if not parts or len(set(parts)) != len(parts) or any(
                part not in ("text", "audio") for part in parts
            ):
                raise ValueError("modalities must be text, audio, or text,audio")
        cleaned = [profile.strip() for profile in self.profiles]
        if not all(cleaned) or len(cleaned) != len(self.profiles):
            raise ValueError("profiles must be nonempty names")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("duplicate profiles are not allowed")
        return self

    @property
    def profile_names(self) -> list[str]:
        return [profile.strip() for profile in self.profiles]

    def prompt_args(self, prompts_path: Optional[Path]) -> list[str]:
        if (self.prompts_text or "").strip():
            return ["--prompts-file", str(prompts_path)]
        if self.prompt:
            return ["--prompt", self.prompt]
        return []

    def common_argv(self, result_path: Path, prompts_path: Optional[Path]) -> list[str]:
        argv = [
            "--url", self.url,
            "--endpoint", self.endpoint,
            "--model", self.model,
            "--namespace", self.namespace,
            "--gateway-name", self.gateway_name,
            "--gateway-container", self.gateway_container,
            "--epp-deployment", self.epp_deployment,
            "--epp-container", self.epp_container,
            "--gateway-wait", str(self.gateway_wait),
            "--epp-wait", str(self.epp_wait),
            "--timeout", str(self.timeout),
            "--output-json", str(result_path),
        ]
        argv += self.prompt_args(prompts_path)
        for setting in self.runs:
            argv += ["--run", f"{setting.iterations}x{setting.concurrency}"]
        if self.endpoint == "/v1/chat/completions":
            argv += ["--tokenizer", self.tokenizer.strip()]
            argv += ["--modalities", self.modalities]
            if self.no_usage:
                argv.append("--no-usage")
        if self.voice:
            argv += ["--voice", self.voice]
        if self.audio_format:
            argv += ["--audio-format", self.audio_format]
        if self.session_length >= 2:
            argv += ["--session-length", str(self.session_length)]
            argv += ["--session-header", self.session_header]
        if self.epp_scores:
            argv.append("--epp-scores")
        if self.no_backend_lookup:
            argv.append("--no-backend-lookup")
        if self.api_key:
            argv += ["--api-key", self.api_key]
        if self.epp_configmap:
            argv += ["--epp-configmap", self.epp_configmap]
        if self.epp_config_key:
            argv += ["--epp-config-key", self.epp_config_key]
        return argv

    def attempt_argv(self, profile: str, result_path: Path, prompts_path: Optional[Path]) -> list[str]:
        return self.common_argv(result_path, prompts_path) + ["--profile", profile]
