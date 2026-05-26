"""Tests for tain_agent.utils.token_utils"""

import pytest
from tain_agent.utils.token_utils import (
    estimate_tokens,
    truncate_text_by_tokens,
    truncate_lines,
)


class TestEstimateTokens:
    def test_short_text(self):
        est = estimate_tokens("hello")
        assert est > 0

    def test_longer_text(self):
        est = estimate_tokens("x" * 1000)
        assert est > 400

    def test_chinese_text(self):
        est = estimate_tokens("你好世界 " * 100)
        assert est > 0

    def test_empty_string(self):
        est = estimate_tokens("")
        assert est >= 1


class TestTruncateTextByTokens:
    def test_no_truncation_small_text(self):
        text = "short text"
        result = truncate_text_by_tokens(text, max_tokens=100)
        assert result == text

    def test_truncation_applied(self):
        text = "A" * 100000
        result = truncate_text_by_tokens(text, max_tokens=100)
        assert len(result) < len(text)
        assert "truncated" in result.lower()
        assert "token" in result.lower()

    def test_head_and_tail_preserved(self):
        head_marker = "START_CONTENT"
        tail_marker = "END_CONTENT"
        text = head_marker + "x" * 50000 + tail_marker
        result = truncate_text_by_tokens(text, max_tokens=100)
        assert head_marker in result[:500]
        assert tail_marker in result[-200:]

    def test_truncation_marker_shows_info(self):
        text = "x" * 100000
        result = truncate_text_by_tokens(text, max_tokens=100)
        assert "100" in result  # max_tokens value appears in marker
        assert "truncated" in result.lower()

    def test_custom_head_ratio(self):
        text = "HEAD" + "x" * 50000 + "TAIL"
        result = truncate_text_by_tokens(text, max_tokens=100, head_ratio=0.8)
        assert "HEAD" in result[:500]
        assert "TAIL" in result[-200:]

    def test_boundary_ratio_clamped(self):
        text = "A" * 100000
        # head_ratio=0.0 clamped to 0.1 — should still have head content
        result = truncate_text_by_tokens(text, max_tokens=100, head_ratio=0.0)
        assert "truncated" in result.lower()
        # head_ratio=1.0 clamped to 0.9 — should still have tail content
        text2 = "START" + "y" * 50000 + "END"
        result2 = truncate_text_by_tokens(text2, max_tokens=100, head_ratio=1.0)
        assert "truncated" in result2.lower()


class TestTruncateLines:
    def test_no_truncation(self):
        text = "line1\nline2\nline3"
        result = truncate_lines(text, max_lines=10)
        assert result == text

    def test_truncation_applied(self):
        text = "\n".join(f"line {i}" for i in range(1000))
        result = truncate_lines(text, max_lines=20)
        assert len(result.split("\n")) < 1000
        assert "truncated" in result

    def test_exact_limit(self):
        text = "\n".join(f"line {i}" for i in range(10))
        result = truncate_lines(text, max_lines=10)
        assert result == text

    def test_preserves_head_and_tail_content(self):
        lines = ["START_MARKER"] + [f"line {i}" for i in range(900)] + ["END_MARKER"]
        text = "\n".join(lines)
        result = truncate_lines(text, max_lines=50)
        assert "START_MARKER" in result
        assert "END_MARKER" in result
