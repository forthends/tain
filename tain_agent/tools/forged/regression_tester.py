
"""regression_tester — Core capability regression test framework.

Tests that the agent's fundamental capabilities are intact:
  1. Basic Python execution environment
  2. Filesystem read/write access
  3. JSON serialization/deserialization
  4. Network connectivity (if available)
  5. Time awareness
  6. String/pattern matching

The tool can also incorporate external test results passed by the caller,
enabling testing of tools that require the full agent context.

Returns a structured report: {passed, failed, skipped, total, tests: [...], summary}
"""

import json
import os
import time as time_module
from datetime import datetime, timezone


def regression_tester(
    external_results: str = "",
    include_network_test: bool = True,
) -> str:
    """Run regression tests on core capabilities.
    
    Args:
        external_results: JSON array of external test results, each as
            {name, passed: bool, detail: str}. 
        include_network_test: Whether to test network connectivity.
    
    Returns:
        Structured test report as JSON string.
    """
    tests: list[dict] = []
    
    # ── Test 1: Basic Python types and operations ──
    _test_basic_python(tests)
    
    # ── Test 2: JSON roundtrip ──
    _test_json(tests)
    
    # ── Test 3: Filesystem access ──
    _test_filesystem(tests)
    
    # ── Test 4: Time/date operations ──
    _test_time(tests)
    
    # ── Test 5: String operations and regex ──
    _test_strings(tests)
    
    # ── Test 6: Collection operations ──
    _test_collections(tests)
    
    # ── Test 7: Network connectivity (optional) ──
    if include_network_test:
        _test_network(tests)
    
    # ── Test 8: Import safety (verify safe modules available) ──
    _test_imports(tests)
    
    # ── Parse external results ──
    if external_results:
        try:
            ext = json.loads(external_results)
            if isinstance(ext, list):
                for item in ext:
                    if isinstance(item, dict):
                        tests.append({
                            "name": item.get("name", "external_test"),
                            "passed": item.get("passed", False),
                            "detail": item.get("detail", ""),
                            "category": "external",
                        })
        except (json.JSONDecodeError, TypeError):
            tests.append({
                "name": "external_results_parse",
                "passed": False,
                "detail": "Failed to parse external_results as JSON array.",
                "category": "meta",
            })
    
    # ── Generate report ──
    passed = sum(1 for t in tests if t.get("passed"))
    failed = sum(1 for t in tests if not t.get("passed"))
    total = len(tests)
    
    report = {
        "passed": passed == total,
        "total": total,
        "passed_count": passed,
        "failed_count": failed,
        "skipped_count": 0,
        "tests": tests,
        "summary": _generate_summary(passed, failed, total),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    return json.dumps(report, ensure_ascii=False, indent=2)


# ── Individual test functions ─────────────────────────────────────────

def _test_basic_python(tests: list) -> None:
    """Test basic Python operations."""
    try:
        # Arithmetic
        assert 1 + 1 == 2
        assert 2 * 3 == 6
        # Type system
        assert isinstance(42, int)
        assert isinstance("hello", str)
        assert isinstance([], list)
        assert isinstance({}, dict)
        # Bool logic
        assert True and True
        assert not False
        # None handling
        assert None is None
        tests.append({"name": "basic_python_types", "passed": True,
                       "detail": "Basic Python types and operations work correctly.",
                       "category": "environment"})
    except Exception as e:
        tests.append({"name": "basic_python_types", "passed": False,
                       "detail": f"Basic Python test failed: {e}", "category": "environment"})


def _test_json(tests: list) -> None:
    """Test JSON serialization roundtrip."""
    try:
        data = {"key": "value", "nested": {"list": [1, 2, 3]}, "unicode": "你好"}
        serialized = json.dumps(data, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized == data
        assert deserialized["nested"]["list"] == [1, 2, 3]
        # Test array serialization
        arr = [1, "two", None, True, {"five": 5}]
        arr_json = json.dumps(arr)
        arr_back = json.loads(arr_json)
        assert arr_back == arr
        tests.append({"name": "json_roundtrip", "passed": True,
                       "detail": "JSON serialization/deserialization works correctly with Unicode.",
                       "category": "data"})
    except Exception as e:
        tests.append({"name": "json_roundtrip", "passed": False,
                       "detail": f"JSON test failed: {e}", "category": "data"})


def _test_filesystem(tests: list) -> None:
    """Test basic filesystem operations."""
    test_file = ".tao_regression_test_tmp"
    try:
        # Write test
        content = f"Regression test at {datetime.now(timezone.utc).isoformat()}"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(content)
        # Read back
        with open(test_file, "r", encoding="utf-8") as f:
            read_back = f.read()
        assert read_back == content
        # Clean up
        os.remove(test_file)
        tests.append({"name": "filesystem_read_write", "passed": True,
                       "detail": "Filesystem read/write/delete works correctly.",
                       "category": "environment"})
    except PermissionError:
        tests.append({"name": "filesystem_read_write", "passed": False,
                       "detail": "Filesystem test failed: permission denied.",
                       "category": "environment"})
    except Exception as e:
        # Attempt cleanup
        try:
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception:
            pass
        tests.append({"name": "filesystem_read_write", "passed": False,
                       "detail": f"Filesystem test failed: {e}", "category": "environment"})


def _test_time(tests: list) -> None:
    """Test time/date operations."""
    try:
        # Get current UTC time
        now = datetime.now(timezone.utc)
        assert now.year >= 2024
        assert 1 <= now.month <= 12
        assert 1 <= now.day <= 31
        # ISO format
        iso = now.isoformat()
        assert "T" in iso
        assert "+00:00" in iso or "Z" in iso or "+" in iso.split("T")[1] if "T" in iso else True
        # Time module
        ts = time_module.time()
        assert ts > 1700000000  # After 2023
        tests.append({"name": "time_operations", "passed": True,
                       "detail": f"Time operations work. Current UTC: {iso[:19]}",
                       "category": "environment"})
    except Exception as e:
        tests.append({"name": "time_operations", "passed": False,
                       "detail": f"Time test failed: {e}", "category": "environment"})


def _test_strings(tests: list) -> None:
    """Test string operations and regex."""
    try:
        # Basic string operations
        s = "Hello, World!"
        assert s.upper() == "HELLO, WORLD!"
        assert s.lower() == "hello, world!"
        assert s.startswith("Hello")
        assert s.endswith("!")
        assert "World" in s
        assert s.replace("World", "Tao") == "Hello, Tao!"
        # Split and join
        parts = s.split(", ")
        assert parts == ["Hello", "World!"]
        assert ", ".join(parts) == s
        # Regex
        import re
        pattern = r"(\w+),?\s*(\w+)!"
        match = re.match(pattern, s)
        assert match is not None
        assert match.group(1) == "Hello"
        assert match.group(2) == "World"
        # Unicode
        unicode_s = "道生一，一生二，二生三，三生万物"
        assert len(unicode_s) > 5
        tests.append({"name": "string_and_regex", "passed": True,
                       "detail": "String operations and regex matching work correctly.",
                       "category": "computation"})
    except Exception as e:
        tests.append({"name": "string_and_regex", "passed": False,
                       "detail": f"String/regex test failed: {e}", "category": "computation"})


def _test_collections(tests: list) -> None:
    """Test collection operations."""
    try:
        # List operations
        lst = [3, 1, 4, 1, 5, 9]
        assert len(lst) == 6
        assert sorted(lst) == [1, 1, 3, 4, 5, 9]
        assert max(lst) == 9
        assert min(lst) == 1
        assert sum(lst) == 23
        # Dict operations
        d = {"a": 1, "b": 2}
        assert d.get("a") == 1
        assert d.get("c", "default") == "default"
        assert set(d.keys()) == {"a", "b"}
        # Set operations
        s1 = {1, 2, 3}
        s2 = {2, 3, 4}
        assert s1 & s2 == {2, 3}
        assert s1 | s2 == {1, 2, 3, 4}
        assert s1 - s2 == {1}
        # Comprehension
        squares = {x: x*x for x in range(5)}
        assert squares[3] == 9
        tests.append({"name": "collection_operations", "passed": True,
                       "detail": "List, dict, set operations and comprehensions work correctly.",
                       "category": "computation"})
    except Exception as e:
        tests.append({"name": "collection_operations", "passed": False,
                       "detail": f"Collection test failed: {e}", "category": "computation"})


def _test_network(tests: list) -> None:
    """Test basic network connectivity."""
    try:
        import urllib.request
        # Try a quick connection to a reliable endpoint
        try:
            req = urllib.request.Request("https://httpbin.org/get", headers={"User-Agent": "Tao-Regression/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                if status == 200:
                    tests.append({"name": "network_connectivity", "passed": True,
                                   "detail": "Network connectivity test passed (httpbin.org reachable).",
                                   "category": "environment"})
                else:
                    tests.append({"name": "network_connectivity", "passed": False,
                                   "detail": f"HTTP returned status {status}.",
                                   "category": "environment"})
        except Exception as e:
            tests.append({"name": "network_connectivity", "passed": False,
                           "detail": f"Network test failed: {type(e).__name__}",
                           "category": "environment"})
    except ImportError:
        tests.append({"name": "network_connectivity", "passed": False,
                       "detail": "urllib.request not available.",
                       "category": "environment"})


def _test_imports(tests: list) -> None:
    """Test that safe/essential modules are importable."""
    essential_modules = [
        ("json", "JSON handling"),
        ("re", "Regular expressions"),
        ("math", "Math operations"),
        ("datetime", "Date/time handling"),
        ("pathlib", "Path manipulation"),
        ("textwrap", "Text wrapping"),
        ("hashlib", "Hash functions"),
        ("base64", "Base64 encoding"),
    ]
    
    for module_name, description in essential_modules:
        try:
            __import__(module_name)
            tests.append({"name": f"import_{module_name}", "passed": True,
                           "detail": f"Module '{module_name}' ({description}) importable.",
                           "category": "imports"})
        except ImportError:
            tests.append({"name": f"import_{module_name}", "passed": False,
                           "detail": f"Module '{module_name}' ({description}) NOT importable.",
                           "category": "imports"})


def _generate_summary(passed: int, failed: int, total: int) -> str:
    """Generate a human-readable summary."""
    if failed == 0:
        return f"ALL {total} TESTS PASSED — Core capabilities intact."
    elif passed == 0:
        return f"ALL {total} TESTS FAILED — Critical degradation detected!"
    else:
        pct = round(passed / total * 100, 1)
        return f"{passed}/{total} TESTS PASSED ({pct}%) — {failed} failures need investigation."
