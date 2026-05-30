"""Tests for the AST-whitelist tool sandbox."""

import pytest
import tain_agent.tools.forged.test_forged_tool as sandbox
import ast

# Alias to avoid pytest collecting the imported function as a test
_test_tool = sandbox.test_forged_tool


class TestSandboxSafeCode:
    def test_simple_safe_tool(self):
        result = _test_tool(
            'import json\ndef main():\n    return json.dumps({"ok": True})'
        )
        assert result["passed"] is True

    def test_multiple_allowed_imports(self):
        result = _test_tool(
            'import json, datetime, pathlib, re, math, collections, itertools, functools, hashlib\n'
            'def main():\n    return str(datetime.datetime.now())'
        )
        assert result["passed"] is True

    def test_allowed_from_import(self):
        result = _test_tool(
            'from datetime import datetime\n'
            'from collections import defaultdict\n'
            'def main():\n    return str(datetime.now())'
        )
        assert result["passed"] is True

    def test_multiple_functions(self):
        result = _test_tool(
            'import json\ndef helper(x):\n    return json.dumps(x)\n'
            'def main():\n    return helper({"ok": True})'
        )
        assert result["passed"] is True


class TestSandboxBlockedImports:
    def test_os_import_blocked(self):
        result = _test_tool('import os\ndef main():\n    os.system("id")')
        assert result["passed"] is False
        assert any(e["type"] == "blocked_import" for e in result["errors"])

    def test_subprocess_import_blocked(self):
        result = _test_tool(
            'import subprocess\ndef main():\n    subprocess.run(["ls"])'
        )
        assert result["passed"] is False
        assert any(e["type"] == "blocked_import" for e in result["errors"])

    def test_sys_import_blocked(self):
        result = _test_tool('import sys\ndef main():\n    return sys.version')
        assert result["passed"] is False

    def test_shutil_import_blocked(self):
        result = _test_tool('import shutil\ndef main():\n    shutil.rmtree("/")')
        assert result["passed"] is False

    def test_socket_import_blocked(self):
        result = _test_tool(
            'import socket\ndef main():\n    socket.gethostbyname("evil.com")'
        )
        assert result["passed"] is False

    def test_ctypes_import_blocked(self):
        result = _test_tool(
            'import ctypes\ndef main():\n    ctypes.CDLL("libc.so.6")'
        )
        assert result["passed"] is False

    def test_from_os_import_blocked(self):
        result = _test_tool('from os import system\ndef main():\n    system("id")')
        assert result["passed"] is False
        assert any(e["type"] == "blocked_import" for e in result["errors"])

    def test_unlisted_module_blocked(self):
        result = _test_tool(
            'import numpy\ndef main():\n    return numpy.array([1,2,3])'
        )
        assert result["passed"] is False
        assert any(e["type"] == "unlisted_import" for e in result["errors"])


class TestSandboxBlockedCalls:
    def test_eval_blocked(self):
        result = _test_tool('def main():\n    eval("1+1")')
        assert result["passed"] is False
        assert any(e["type"] == "blocked_call" for e in result["errors"])

    def test_exec_blocked(self):
        result = _test_tool('def main():\n    exec("x=1")')
        assert result["passed"] is False
        assert any(e["type"] == "blocked_call" for e in result["errors"])

    def test_compile_blocked(self):
        result = _test_tool('def main():\n    compile("x=1", "", "exec")')
        assert result["passed"] is False
        assert any(e["type"] == "blocked_call" for e in result["errors"])

    def test_dunder_import_blocked(self):
        result = _test_tool(
            'def main():\n    __import__("os").system("id")'
        )
        assert result["passed"] is False
        assert any(e["type"] == "blocked_call" for e in result["errors"])

    def test_open_blocked(self):
        result = _test_tool(
            'def main():\n    open("/etc/passwd").read()'
        )
        assert result["passed"] is False
        assert any(e["type"] == "blocked_call" for e in result["errors"])


class TestSandboxEdgeCases:
    def test_no_functions_fails(self):
        result = _test_tool('x = 1')
        assert result["passed"] is False
        assert any(e["type"] == "no_functions" for e in result["errors"])

    def test_syntax_error_fails(self):
        result = _test_tool('def main(:\n    pass')
        assert result["passed"] is False
        assert any(e["type"] == "syntax_error" for e in result["errors"])

    def test_absolute_path_warns(self):
        result = _test_tool('def main():\n    path = "/etc/passwd"\n    return path')
        assert result["passed"] is True
        assert len(result["warnings"]) >= 1

    def test_parent_dir_traversal_warns(self):
        result = _test_tool(
            'def main():\n    path = "../outside/file.txt"\n    return path'
        )
        assert len(result["warnings"]) >= 1


class TestImportMapBuilder:
    def test_simple_import(self):
        tree = ast.parse('import os\nx = 1')
        m = sandbox._build_import_map(tree)
        assert m == {"os": "os"}

    def test_aliased_import(self):
        tree = ast.parse('import numpy as np\nx = 1')
        m = sandbox._build_import_map(tree)
        assert m == {"np": "numpy"}

    def test_from_import(self):
        tree = ast.parse('from os import system\nsystem("id")')
        m = sandbox._build_import_map(tree)
        assert m == {"system": "os.system"}

    def test_from_import_alias(self):
        tree = ast.parse('from os import path as p\nx = p.join("a", "b")')
        m = sandbox._build_import_map(tree)
        assert m == {"p": "os.path"}
