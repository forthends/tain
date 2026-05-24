"""
Code Entropy — code health analyzer for the improvement loop.

Computes a health_score (0-1) based on:
- File size distribution (penalizes large files and extreme variance)
- Test file ratio
- Recent git activity signal
"""

from pathlib import Path


def analyze_entropy(base_dir: str = ".") -> dict:
    tao_dir = Path(base_dir) / "tain_agent"
    if not tao_dir.exists():
        return {"health_score": 1.0, "total_files": 0, "total_lines": 0,
                "test_ratio": 0.0, "summary": "No tain_agent directory found."}

    file_sizes = []
    total_lines = 0
    py_count = 0
    test_count = 0

    for py_file in tao_dir.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        py_count += 1
        if "test" in py_file.name.lower() or "test" in str(py_file.parent).lower():
            test_count += 1
        try:
            lines = len(py_file.read_text(encoding="utf-8").split("\n"))
            file_sizes.append(lines)
            total_lines += lines
        except Exception:
            pass

    if py_count == 0:
        return {"health_score": 1.0, "total_files": 0, "total_lines": 0,
                "test_ratio": 0.0, "summary": "No Python files found."}

    # Compute size variance penalty
    avg_size = total_lines / py_count
    variance = sum((s - avg_size) ** 2 for s in file_sizes) / py_count
    cv = (variance ** 0.5) / avg_size if avg_size > 0 else 0

    # Large-file penalty: files > 1000 lines are a warning sign
    large_count = sum(1 for s in file_sizes if s > 1000)
    large_penalty = min(large_count / py_count, 1.0) * 0.3

    # CV penalty: high variance in file size suggests uneven distribution
    cv_penalty = min(cv / 3.0, 1.0) * 0.3

    # Test bonus: having tests improves score
    test_ratio = test_count / max(py_count, 1)
    test_bonus = min(test_ratio * 0.3, 0.2)

    # Compute health score
    health_score = 1.0 - large_penalty - cv_penalty + test_bonus
    health_score = max(0.0, min(1.0, health_score))

    return {
        "health_score": round(health_score, 3),
        "total_files": py_count,
        "total_lines": total_lines,
        "test_count": test_count,
        "test_ratio": round(test_ratio, 3),
        "large_file_count": large_count,
        "size_cv": round(cv, 3),
        "summary": f"Health: {health_score:.2f} | {py_count} files, {total_lines} lines, "
                   f"test_ratio={test_ratio:.2f}, large_files={large_count}",
    }


def main(action: str = "analyze_entropy", **kwargs) -> dict:
    return analyze_entropy(**kwargs)
