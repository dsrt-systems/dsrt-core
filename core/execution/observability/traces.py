# Path: core/execution/observability/traces.py
"""
Execution Trace Collector & Secret Redactor.
Records execution spans, step events, token metrics, costs, and timings while redacting sensitive tokens.
"""

import re
import uuid
import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Redactor:
    """Utility for sanitizing secrets, API keys, and authorization headers from strings and dictionaries."""

    # Patterns matching common sensitive keys and tokens
    SECRET_KEY_PATTERNS = [
        re.compile(r"api[-_]?key", re.IGNORECASE),
        re.compile(r"secret", re.IGNORECASE),
        re.compile(r"password", re.IGNORECASE),
        re.compile(r"authorization", re.IGNORECASE),
        re.compile(r"bearer", re.IGNORECASE),
        re.compile(r"token", re.IGNORECASE),
        re.compile(r"private[-_]?key", re.IGNORECASE),
    ]

    SENSITIVE_VALUE_REGEXES = [
        re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),  # OpenAI/Anthropic style key
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),
        re.compile(r"ghp_[a-zA-Z0-9]{36}"),    # GitHub PAT
    ]

    REDACTED_SUBSTITUTE = "[REDACTED]"

    @classmethod
    def redact_string(cls, text: str) -> str:
        """Redacts sensitive value patterns from plain text strings."""
        if not text:
            return text
        sanitized = text
        for pattern in cls.SENSITIVE_VALUE_REGEXES:
            sanitized = pattern.sub(cls.REDACTED_SUBSTITUTE, sanitized)
        return sanitized

    @classmethod
    def redact_data(cls, data: Any) -> Any:
        """Recursively traverses dictionaries, lists, and primitives to redact sensitive fields."""
        if isinstance(data, str):
            return cls.redact_string(data)
        elif isinstance(data, dict):
            cleaned: Dict[str, Any] = {}
            for key, val in data.items():
                is_sensitive_key = any(pattern.search(str(key)) for pattern in cls.SECRET_KEY_PATTERNS)
                if is_sensitive_key:
                    cleaned[key] = cls.REDACTED_SUBSTITUTE
                else:
                    cleaned[key] = cls.redact_data(val)
            return cleaned
        elif isinstance(data, list):
            return [cls.redact_data(item) for item in data]
        elif isinstance(data, tuple):
            return tuple(cls.redact_data(item) for item in data)
        return data


class TraceSpan(BaseModel):
    """Represents a single atomic operation or execution step span."""

    span_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    step_index: int
    name: str
    step_type: str
    status: str = "RUNNING"
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    error_message: Optional[str] = None
    started_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    completed_at: Optional[datetime.datetime] = None

    def complete(
        self,
        status: str = "COMPLETED",
        outputs: Optional[Dict[str, Any]] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        error_message: Optional[str] = None,
    ) -> None:
        """Marks the span as completed and aggregates execution metrics."""
        self.status = status
        if outputs is not None:
            self.outputs = Redactor.redact_data(outputs)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd
        self.error_message = Redactor.redact_string(error_message) if error_message else None
        self.completed_at = datetime.datetime.now(datetime.timezone.utc)
        
        start_ts = self.started_at.timestamp()
        end_ts = self.completed_at.timestamp()
        self.duration_ms = int((end_ts - start_ts) * 1000)


class TraceCollector:
    """In-memory trace collector that builds and sanitizes structured execution traces."""

    def __init__(self, trace_id: str, execution_id: str):
        self.trace_id = trace_id
        self.execution_id = execution_id
        self.spans: List[TraceSpan] = []
        self._step_counter = 0
        self.created_at = datetime.datetime.now(datetime.timezone.utc)
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def start_span(self, name: str, step_type: str, inputs: Optional[Dict[str, Any]] = None) -> TraceSpan:
        """Starts a new trace span with redacted input metadata."""
        self._step_counter += 1
        sanitized_inputs = Redactor.redact_data(inputs or {})
        span = TraceSpan(
            trace_id=self.trace_id,
            step_index=self._step_counter,
            name=name,
            step_type=step_type,
            inputs=sanitized_inputs,
        )
        self.spans.append(span)
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)
        return span

    def get_span(self, span_id: str) -> Optional[TraceSpan]:
        """Retrieves a span by its identifier."""
        for s in self.spans:
            if s.span_id == span_id:
                return s
        return None

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.spans)

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.spans)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.spans)

    @property
    def total_duration_ms(self) -> int:
        return sum(s.duration_ms for s in self.spans)

    @property
    def step_count(self) -> int:
        return len(self.spans)

    def to_summary(self) -> Dict[str, Any]:
        """Produces a sanitized execution trace summary dictionary."""
        return {
            "trace_id": self.trace_id,
            "execution_id": self.execution_id,
            "step_count": self.step_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_duration_ms": self.total_duration_ms,
            "spans": [s.model_dump(mode="json") for s in self.spans],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }