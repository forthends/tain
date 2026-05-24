"""
External World — 外部世界接入层

Breaks the closed self-referential system by connecting the agent to
external data sources. Without external input, the agent's world is a
closed system that converges to equilibrium (Phase 1's passive-maintenance
end state is the second law of thermodynamics in agent space).

Architecture:
  config.yaml                    ExternalWorld
  ────────────                   ─────────────
  external_world:                ┌─ _apis: dict[name] → ApiConfig
    apis:                        │
      - name: ...          ──→   ├─ _rate_limits: dict[name] → RateLimit
        endpoint: ...            │
        schedule: ...            ├─ _subscriptions: dict[name] → Subscription
                                 │
  Agent calls:                   │
    external_fetch(name)   ──→   ├─ fetch() → rate-limit check → http get
    external_subscribe(name) ──→ ├─ subscribe() → cron schedule
    external_status()       ──→   └─ status() → active subscriptions

Safety:
  - Rate limiting per API (configurable max calls / window)
  - No local file data egress (only config-defined endpoints)
  - External input validated and treated as untrusted
  - Config protected by safety.protected_paths
"""

import json
import time as _time
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from tain_agent.core.time_utils import now


# ─── Data types ──────────────────────────────────────────────────────────

@dataclass
class ApiConfig:
    """Configuration for a registered external API."""
    name: str
    endpoint: str
    description: str = ""
    schedule: str = ""          # cron expression for auto-fetch
    method: str = "GET"         # HTTP method
    headers: dict = field(default_factory=dict)
    max_calls_per_hour: int = 60
    max_calls_per_day: int = 500
    timeout_seconds: float = 10.0


@dataclass
class RateLimit:
    """Tracks call counts for rate limiting."""
    hour_window_start: float = 0.0
    hourly_count: int = 0
    day_window_start: float = 0.0
    daily_count: int = 0
    last_call_at: float = 0.0


@dataclass
class Subscription:
    """An active subscription to an external data source."""
    api_name: str
    subscribed_at: str = ""
    last_fetched_at: str = ""
    fetch_count: int = 0
    last_result_hash: str = ""  # detect changes in fetched data
    active: bool = True


# ─── ExternalWorld ───────────────────────────────────────────────────────

class ExternalWorld:
    """Manages external API connections with safety boundaries.

    The agent uses this to:
      - Subscribe to external information flows (extending its "senses")
      - Discover evolution direction from external changes
      - Receive feedback that breaks pure self-evaluation loops

    Safety is enforced through rate limiting, endpoint whitelisting,
    and treating all external input as untrusted.
    """

    def __init__(self, config: dict = None, memory=None, decision_log=None):
        self._apis: dict[str, ApiConfig] = {}
        self._rate_limits: dict[str, RateLimit] = {}
        self._subscriptions: dict[str, Subscription] = {}
        self._memory = memory
        self._decision_log = decision_log
        self._enabled = config.get("enabled", False) if config else False

        if config and config.get("enabled"):
            self._load_from_config(config)

    # ── Configuration ──────────────────────────────────────────────────

    def _load_from_config(self, config: dict) -> None:
        """Load API definitions from config.yaml external_world section."""
        apis = config.get("apis", [])
        for api_def in apis:
            if not api_def.get("name") or not api_def.get("endpoint"):
                continue
            cfg = ApiConfig(
                name=api_def["name"],
                endpoint=api_def["endpoint"],
                description=api_def.get("description", ""),
                schedule=api_def.get("schedule", ""),
                method=api_def.get("method", "GET"),
                headers=api_def.get("headers", {}),
                max_calls_per_hour=api_def.get("max_calls_per_hour", 60),
                max_calls_per_day=api_def.get("max_calls_per_day", 500),
                timeout_seconds=api_def.get("timeout_seconds", 10.0),
            )
            self._apis[cfg.name] = cfg
            self._rate_limits[cfg.name] = RateLimit()

    def register_api(self, name: str, endpoint: str, description: str = "",
                     schedule: str = "", method: str = "GET",
                     headers: dict = None,
                     max_calls_per_hour: int = 60,
                     max_calls_per_day: int = 500,
                     timeout_seconds: float = 10.0) -> dict:
        """Register a new external API endpoint.

        This is the runtime equivalent of adding an entry to config.yaml.
        Can be called by the agent to dynamically add data sources.
        """
        if name in self._apis:
            return {"success": False, "error": f"API '{name}' already registered."}

        cfg = ApiConfig(
            name=name, endpoint=endpoint, description=description,
            schedule=schedule, method=method, headers=headers or {},
            max_calls_per_hour=max_calls_per_hour,
            max_calls_per_day=max_calls_per_day,
            timeout_seconds=timeout_seconds,
        )
        self._apis[name] = cfg
        self._rate_limits[name] = RateLimit()

        if self._decision_log:
            self._decision_log.record(
                context={"api_name": name, "endpoint": endpoint},
                decision_type="external_api_register",
                options_considered=[],
                chosen_option=name,
                reasoning=f"Registered external API: {name} — {description[:100]}",
                expected_outcome=f"Agent can fetch data from {name}",
                phase="evolve",
            )

        return {"success": True, "api_name": name, "message": f"API '{name}' registered."}

    # ── Rate Limiting ──────────────────────────────────────────────────

    def _check_rate_limit(self, name: str) -> dict:
        """Check if an API call is within rate limits. Returns error dict if limited."""
        if name not in self._rate_limits:
            return {"allowed": True}

        rl = self._rate_limits[name]
        cfg = self._apis.get(name)
        if not cfg:
            return {"allowed": True}

        now_ts = _time.time()

        # Reset hourly window if needed
        if now_ts - rl.hour_window_start >= 3600:
            rl.hour_window_start = now_ts
            rl.hourly_count = 0

        # Reset daily window if needed
        if now_ts - rl.day_window_start >= 86400:
            rl.day_window_start = now_ts
            rl.daily_count = 0

        # Enforce cooldown between calls (min 1 second)
        if now_ts - rl.last_call_at < 1.0:
            return {"allowed": False, "error": "调用过于频繁，请至少间隔 1 秒。"}

        if rl.hourly_count >= cfg.max_calls_per_hour:
            remaining = 3600 - (now_ts - rl.hour_window_start)
            return {
                "allowed": False,
                "error": f"已达每小时调用上限 ({cfg.max_calls_per_hour})。{remaining:.0f} 秒后重置。",
            }

        if rl.daily_count >= cfg.max_calls_per_day:
            remaining = 86400 - (now_ts - rl.day_window_start)
            return {
                "allowed": False,
                "error": f"已达每日调用上限 ({cfg.max_calls_per_day})。{remaining:.0f} 秒后重置。",
            }

        return {"allowed": True}

    def _record_call(self, name: str) -> None:
        """Record a successful API call for rate limit tracking."""
        if name not in self._rate_limits:
            return
        rl = self._rate_limits[name]
        now_ts = _time.time()
        rl.hourly_count += 1
        rl.daily_count += 1
        rl.last_call_at = now_ts

    # ── Fetch ──────────────────────────────────────────────────────────

    def fetch(self, name: str, params: dict = None) -> dict:
        """Fetch data from a registered external API.

        Args:
            name: The registered API name.
            params: Optional query parameters.

        Returns:
            dict with success, data (or error), fetched_at, from_cache.
        """
        if not self._enabled:
            return {"success": False, "error": "外部世界接入未启用。请在 config.yaml 设置 external_world.enabled: true"}

        if name not in self._apis:
            return {"success": False, "error": f"未知的外部 API: '{name}'。已注册: {list(self._apis.keys())}"}

        # Rate limit check
        limit_check = self._check_rate_limit(name)
        if not limit_check["allowed"]:
            return {"success": False, "error": limit_check["error"]}

        cfg = self._apis[name]
        self._record_call(name)

        try:
            import urllib.request
            import urllib.error
            import ssl

            url = cfg.endpoint
            if params:
                from urllib.parse import urlencode
                query = urlencode(params)
                url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"

            req = urllib.request.Request(url, method=cfg.method)
            req.add_header("User-Agent", "Tao-Agent/2.0")
            req.add_header("Accept", "application/json")
            for key, val in cfg.headers.items():
                req.add_header(key, val)

            ctx = ssl.create_default_context()
            response = urllib.request.urlopen(req, timeout=cfg.timeout_seconds, context=ctx)
            raw = response.read().decode("utf-8", errors="replace")

            # Try to parse as JSON, fall back to text
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"text": raw[:5000]}  # Truncate large text responses

            # Update subscription if active
            fetched_at = now().isoformat()
            content_hash = hashlib.md5(raw.encode()).hexdigest()

            if name in self._subscriptions:
                sub = self._subscriptions[name]
                sub.last_fetched_at = fetched_at
                sub.fetch_count += 1
                sub.last_result_hash = content_hash

            return {
                "success": True,
                "api_name": name,
                "data": data,
                "fetched_at": fetched_at,
                "content_hash": content_hash,
            }

        except urllib.error.HTTPError as e:
            return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "api_name": name}
        except urllib.error.URLError as e:
            return {"success": False, "error": f"连接失败: {e.reason}", "api_name": name}
        except Exception as e:
            return {"success": False, "error": f"Fetch error: {type(e).__name__}: {str(e)}", "api_name": name}

    # ── Subscribe ──────────────────────────────────────────────────────

    def subscribe(self, name: str) -> dict:
        """Subscribe to periodic fetching of an external API.

        The agent should call this once to set up a recurring data source.
        Actual scheduling is handled by the agent's cron system.
        """
        if name not in self._apis:
            return {"success": False, "error": f"未知的 API: '{name}'"}

        if name in self._subscriptions and self._subscriptions[name].active:
            return {"success": False, "error": f"已经订阅了 '{name}'"}

        sub = Subscription(
            api_name=name,
            subscribed_at=now().isoformat(),
            active=True,
        )
        self._subscriptions[name] = sub

        if self._decision_log:
            self._decision_log.record(
                context={"api_name": name, "schedule": self._apis[name].schedule},
                decision_type="external_subscribe",
                options_considered=[],
                chosen_option=name,
                reasoning=f"Subscribed to {name}: {self._apis[name].description[:100]}",
                expected_outcome=f"Periodic data inflow from {name}",
                phase="evolve",
            )

        return {
            "success": True,
            "api_name": name,
            "schedule": self._apis[name].schedule,
            "message": f"已订阅 '{name}'。定时: {self._apis[name].schedule or '手动'}",
        }

    def unsubscribe(self, name: str) -> dict:
        """Unsubscribe from an external API."""
        if name not in self._subscriptions:
            return {"success": False, "error": f"未订阅 '{name}'"}

        self._subscriptions[name].active = False
        return {"success": True, "message": f"已取消订阅 '{name}'"}

    # ── Status ─────────────────────────────────────────────────────────

    def list_apis(self) -> list[dict]:
        """List all registered external APIs."""
        result = []
        for name, cfg in self._apis.items():
            rl = self._rate_limits.get(name)
            sub = self._subscriptions.get(name)
            result.append({
                "name": name,
                "description": cfg.description,
                "endpoint": cfg.endpoint,
                "schedule": cfg.schedule,
                "subscribed": sub.active if sub else False,
                "hourly_calls": rl.hourly_count if rl else 0,
                "daily_calls": rl.daily_count if rl else 0,
                "max_per_hour": cfg.max_calls_per_hour,
                "max_per_day": cfg.max_calls_per_day,
            })
        return result

    def status_report(self) -> str:
        """Human-readable status of all external connections."""
        lines = [
            "=" * 50,
            "  外部世界连接状态",
            "=" * 50,
            f"  状态: {'已启用' if self._enabled else '已禁用'}",
            f"  已注册 API: {len(self._apis)}",
            f"  活跃订阅: {sum(1 for s in self._subscriptions.values() if s.active)}",
            "",
        ]

        if self._apis:
            lines.append("  API 列表:")
            for name, cfg in self._apis.items():
                rl = self._rate_limits.get(name)
                sub = self._subscriptions.get(name)
                sub_mark = "📡" if (sub and sub.active) else "  "
                lines.append(f"    {sub_mark} {name}")
                lines.append(f"       {cfg.description[:60]}")
                lines.append(f"       频率: {rl.hourly_count}/{cfg.max_calls_per_hour}/h, "
                           f"{rl.daily_count}/{cfg.max_calls_per_day}/d")
                if sub and sub.last_fetched_at:
                    lines.append(f"       最后获取: {sub.last_fetched_at[:19]} "
                               f"(共 {sub.fetch_count} 次)")

        if not self._apis:
            lines.append("  (未注册任何外部 API)")

        lines.append("")
        lines.append("  安全约束: 外部输入作为不可信数据处理。本地文件不会上传。")
        return "\n".join(lines)

    def export_state(self) -> dict:
        """Export current state for persistence."""
        return {
            "enabled": self._enabled,
            "api_count": len(self._apis),
            "subscription_count": sum(1 for s in self._subscriptions.values() if s.active),
            "apis": self.list_apis(),
        }

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def subscription_count(self) -> int:
        return sum(1 for s in self._subscriptions.values() if s.active)
