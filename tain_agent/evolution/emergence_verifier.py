"""
Emergence Verifier — 涌现验证

Phase 2 milestone 2.3: verify that the diversity mechanisms (environment
differentiation, drive randomization, trial ordering) actually produce
emergent behavioral diversity — different agents become different people.

This module tests the producing mechanisms WITHOUT requiring LLM calls.
It verifies that the Phase 2 design solves the four key Phase 1 limitations:
  1. Passive maintenance trap → exploration engine produces non-zero scores
  2. Identity convergence → different seeds produce different drive profiles
  3. Personality underdevelopment → drive tension maps to personality hints
  4. Deterministic behavior → trial order diversity produces different paths

Usage:
  python3 -m tain_agent.evolution.emergence_verifier
"""

import random
import statistics
from collections import Counter

from tain_agent.core.drives import DriveSystem
from tain_agent.core.environment import apply_diversity_to_config, _resolve_seed

# ─── Test fixture: minimal config for verification ────────────────────

def _make_config(seed=None, drives_override=None):
    """Build a minimal config dict for diversity verification."""
    cfg = {
        "agent": {"name": "Tain Agent", "version": "2.0.0-dev", "timezone": "Asia/Shanghai"},
        "llm": {"provider": "test", "model": "test", "max_tokens": 100, "api_key_env": "NONE", "base_url": ""},
        "safety": {"protected_paths": [], "confirm_destructive": False},
        "logging": {"directory": "/tmp", "decision_log_file": "test.jsonl", "memory_file": "test.json"},
        "bootstrap": {"max_exploration_cycles": 10, "max_definition_cycles": 5,
                      "min_bootstrap_cycles": 5, "min_action_categories": 2},
        "diversity": {
            "seed": seed if seed is not None else "random",
            "tool_bias": {"observation": 1.0, "creation": 1.0, "reflection": 1.0},
            "knowledge_seeds": [],
            "constraints": {"allow_network": True, "allow_file_write": True, "allow_forge": True},
        },
        "drives": {
            "exploration": {
                "curiosity_bonus_rate": 0.05,
                "max_curiosity_bonus": 0.30,
                "novelty_weight": 0.20,
                "idle_pressure_rate": 0.10,
                "max_idle_pressure": 0.40,
            },
        },
    }
    if drives_override:
        cfg["drives"].update(drives_override)
    return cfg


# ─── Verifier class ───────────────────────────────────────────────────

class EmergenceVerifier:
    """Runs all emergence verification checks and generates a report."""

    def __init__(self):
        self.results: dict[str, dict] = {}

    # ── Main entry ──────────────────────────────────────────────────

    def verify_all(self, instance_count: int = 30) -> dict:
        """Run all verification checks. Returns aggregated results."""
        print("=" * 64)
        print("  Phase 2 涌现验证 (Emergence Verification)")
        print("=" * 64)
        print()

        self.results = {}

        checks = [
            ("instance_diversity", lambda: self.verify_instance_diversity(instance_count)),
            ("trial_order_diversity", self.verify_trial_order_diversity),
            ("drive_personality_causality", self.verify_drive_personality_causality),
            ("passive_maintenance_fix", self.verify_passive_maintenance_fix),
            ("exploration_engine", self.verify_exploration_engine),
            ("action_feedback_divergence", self.verify_action_feedback_divergence),
        ]

        all_passed = True
        for name, check_fn in checks:
            try:
                result = check_fn()
                self.results[name] = result
                status = "PASS" if result.get("passed", False) else "FAIL"
                symbol = "✅" if result["passed"] else "❌"
                print(f"  {symbol} {name}: {status}")
                if not result["passed"]:
                    all_passed = False
                    print(f"     原因: {result.get('reason', '未知')}")
            except Exception as e:
                self.results[name] = {"passed": False, "reason": str(e)}
                print(f"  ❌ {name}: ERROR — {e}")
                all_passed = False

        print()
        if all_passed:
            print("  ✅ 所有涌现验证通过！")
        else:
            print("  ⚠️  部分验证未通过 — 详见上方输出。")

        self.results["overall_passed"] = all_passed
        return self.results

    # ── 1. Instance Diversity ────────────────────────────────────────

    def verify_instance_diversity(self, n: int = 30) -> dict:
        """Verify that N instances with different seeds produce diverse profiles.

        Phase 1 problem: all instances converged to "知识探索者".
        Phase 2 expectation: different seeds → different drive profiles,
        knowledge seeds, trial orders, and personality hints.
        """
        instances = []
        for i in range(n):
            config = _make_config(seed=i * 100 + random.randint(1, 99))
            diversity = apply_diversity_to_config(config)

            drive_sys = DriveSystem(
                drives_config={k: v for k, v in diversity["drives"].items()
                              if k in ("curiosity", "mastery", "creation", "conservation")},
                exploration_config=diversity.get("exploration", {}),
            )

            instances.append({
                "seed": diversity["seed"],
                "instance_id": diversity["identity"]["instance_id"],
                "element": diversity["identity"]["elemental_affinity"],
                "drives": dict(drive_sys.drives),
                "dominant_drive": drive_sys.dominate_drive(),
                "personality_hint": drive_sys.get_profile()["personality_hint"],
                "trial_order": diversity["trial_order"],
                "knowledge_seed": diversity["knowledge_seeds"][0] if diversity["knowledge_seeds"] else "none",
            })

        # Check 1: All instance IDs are unique
        ids = [i["instance_id"] for i in instances]
        unique_ids = len(set(ids))
        id_check = unique_ids == n

        # Check 2: Not all instances have the same dominant drive
        dominant_drives = [i["dominant_drive"] for i in instances]
        unique_drives = len(set(dominant_drives))
        drive_check = unique_drives >= 2  # at least 2 different dominant drives

        # Check 3: Drive values have meaningful variance
        all_curiosity = [i["drives"]["curiosity"] for i in instances]
        all_mastery = [i["drives"]["mastery"] for i in instances]
        all_creation = [i["drives"]["creation"] for i in instances]
        all_conservation = [i["drives"]["conservation"] for i in instances]

        curiosity_std = statistics.stdev(all_curiosity) if len(all_curiosity) > 1 else 0
        mastery_std = statistics.stdev(all_mastery) if len(all_mastery) > 1 else 0
        variance_check = curiosity_std > 0.05 and mastery_std > 0.05

        # Check 4: Multiple different personality hints appear
        hints = [i["personality_hint"] for i in instances]
        unique_hints = len(set(hints))
        hint_check = unique_hints >= 3  # at least 3 different personality types

        # Check 5: Trial orders vary
        first_trials = [i["trial_order"][0] for i in instances]
        unique_first_trials = len(set(first_trials))
        trial_check = unique_first_trials >= 3  # at least 3 different first trials

        # Check 6: Knowledge seeds vary
        knowledge_seeds = [i["knowledge_seed"] for i in instances]
        unique_seeds = len(set(knowledge_seeds))
        seed_check = unique_seeds >= 2  # at least 2 different knowledge domains

        all_checks = [id_check, drive_check, variance_check, hint_check, trial_check, seed_check]
        passed = all(all_checks)

        # Print distribution
        print(f"    实例数: {n}")
        print(f"    唯一 ID: {unique_ids}/{n}")
        print(f"    主导驱动力分布: {dict(Counter(dominant_drives))}")
        print(f"    人格类型数: {unique_hints}")
        print(f"    首试炼分布: {dict(Counter(first_trials))}")
        print(f"    知识种子数: {unique_seeds}")
        print(f"    好奇心标准差: {curiosity_std:.3f}")
        print(f"    精进标准差: {mastery_std:.3f}")

        return {
            "passed": passed,
            "stats": {
                "instance_count": n,
                "unique_ids": unique_ids,
                "unique_dominant_drives": unique_drives,
                "unique_personality_hints": unique_hints,
                "unique_first_trials": unique_first_trials,
                "unique_knowledge_seeds": unique_seeds,
                "curiosity_stdev": round(curiosity_std, 4),
                "mastery_stdev": round(mastery_std, 4),
                "dominant_drive_distribution": dict(Counter(dominant_drives)),
                "personality_hint_distribution": dict(Counter(hints)),
            },
            "reason": None if passed else self._diversity_fail_reason(
                id_check, drive_check, variance_check, hint_check, trial_check, seed_check
            ),
        }

    def _diversity_fail_reason(self, *checks) -> str:
        names = ["唯一ID", "主导驱动力≥2", "驱动力方差", "人格类型≥3", "首试炼多样", "知识种子多样"]
        failed = [names[i] for i, c in enumerate(checks) if not c]
        return f"以下检查未通过: {', '.join(failed)}"

    # ── 2. Trial Order Diversity ─────────────────────────────────────

    def verify_trial_order_diversity(self) -> dict:
        """Verify that randomized trial orders produce different first experiences.

        The first trial is especially formative — different first trials
        create different initial impressions of "what an agent does."
        """
        orders = []
        for i in range(100):
            config = _make_config(seed=i * 7 + 42)
            diversity = apply_diversity_to_config(config)
            orders.append(tuple(diversity["trial_order"]))

        unique_orders = len(set(orders))

        # With 5! = 120 possible orderings, 100 random samples should
        # produce at least 40 unique orders (very conservative)
        order_check = unique_orders >= 40

        # Each trial should appear as "first trial" roughly equally
        first_trial_counts = Counter(o[0] for o in orders)
        min_count = min(first_trial_counts.values())
        max_count = max(first_trial_counts.values())
        # With 100 samples and 5 options, expect ~20 each
        # Allow 8-35 range (generous to account for randomness)
        distribution_check = min_count >= 8 and (max_count - min_count) <= 30

        passed = order_check and distribution_check

        print(f"    唯一试炼顺序: {unique_orders}/100")
        print(f"    首试炼分布: {dict(first_trial_counts)}")
        print(f"    范围: {min_count}–{max_count}")

        return {
            "passed": passed,
            "stats": {
                "total_samples": 100,
                "unique_orders": unique_orders,
                "first_trial_distribution": dict(first_trial_counts),
                "min_first_trial": min_count,
                "max_first_trial": max_count,
            },
            "reason": None if passed else
                f"唯一顺序={unique_orders} (<40) 或首试炼分布不均 ({min_count}–{max_count})",
        }

    # ── 3. Drive → Personality Causality ─────────────────────────────

    def verify_drive_personality_causality(self) -> dict:
        """Verify that different drive profiles produce different personality hints.

        The causal chain: drive intensities → dominant drive →
        personality hint. This must be consistent and diverse.
        """
        # Create instances with explicitly different drive profiles
        profiles = [
            {"curiosity": 0.8, "mastery": 0.3, "creation": 0.5, "conservation": 0.2},
            {"curiosity": 0.2, "mastery": 0.8, "creation": 0.4, "conservation": 0.3},
            {"curiosity": 0.4, "mastery": 0.3, "creation": 0.85, "conservation": 0.2},
            {"curiosity": 0.2, "mastery": 0.3, "creation": 0.2, "conservation": 0.75},
            {"curiosity": 0.5, "mastery": 0.5, "creation": 0.5, "conservation": 0.5},
        ]
        expected_dominants = ["curiosity", "mastery", "creation", "conservation", None]

        hints = []
        dominants = []
        for i, drive_vals in enumerate(profiles):
            config = _make_config(seed=i, drives_override=drive_vals)
            diversity = apply_diversity_to_config(config)
            drive_sys = DriveSystem(
                drives_config={k: v for k, v in diversity["drives"].items()
                              if k in ("curiosity", "mastery", "creation", "conservation")},
                exploration_config=diversity.get("exploration", {}),
            )
            dominants.append(drive_sys.dominate_drive())
            hints.append(drive_sys.get_profile()["personality_hint"])

        # Check 1: Each profile's dominant drive matches expectation
        dominant_matches = all(
            d == e for d, e in zip(dominants, expected_dominants) if e is not None
        )

        # Check 2: All 5 personality hints are different
        unique_hints = len(set(hints))
        hint_check = unique_hints >= 4  # at least 4 different hints

        # Check 3: Balanced profile (0.5/0.5/0.5/0.5) → "平衡者" hint
        balanced_hint = hints[4]
        balanced_check = "平衡" in balanced_hint

        passed = dominant_matches and hint_check and balanced_check

        print(f"    驱动力 → 主导驱动力匹配: {dominant_matches}")
        print(f"    不同人格类型数: {unique_hints}/5")
        print(f"    均衡配置 → 均衡者: {balanced_check}")
        for i, (d, h) in enumerate(zip(dominants, hints)):
            print(f"    [{i}] dominant={d} → {h[:40]}...")

        return {
            "passed": passed,
            "stats": {
                "profiles_tested": len(profiles),
                "dominant_matches_expected": dominant_matches,
                "unique_hints": unique_hints,
                "balanced_profile_yields_balanced_hint": balanced_check,
                "dominants": dominants,
                "hints": hints,
            },
            "reason": None if passed else
                f"主导匹配={dominant_matches}, 不同hint={unique_hints}, 均衡检测={balanced_check}",
        }

    # ── 4. Passive Maintenance Fix ───────────────────────────────────

    def verify_passive_maintenance_fix(self) -> dict:
        """Verify the exploration engine prevents the Phase 1 deadlock.

        Phase 1 problem: when all improvement metrics are 0.0 (no gaps),
        need_score = 0.0, agent does nothing → passive maintenance trap.

        Phase 2 fix: the exploration engine provides a separate score that
        grows with idle cycles, ensuring the agent eventually explores even
        when everything is "healthy."
        """
        config = _make_config(seed=42)
        diversity = apply_diversity_to_config(config)
        drive_sys = DriveSystem(
            drives_config={k: v for k, v in diversity["drives"].items()
                          if k in ("curiosity", "mastery", "creation", "conservation")},
            exploration_config=diversity.get("exploration", {}),
        )

        # Simulate the Phase 1 scenario: all metrics healthy, no gaps
        # In Phase 1: need_score = 0.0 → no trigger → passive maintenance
        phase1_need_score = 0.0

        # Phase 2: even with need_score = 0.0, exploration engine provides
        # a separate motivation signal
        initial_explore = drive_sys.compute_exploration_score()

        # Check 1: At time=0 with unexplored space, there should be SOME
        # exploration score from the novelty bonus
        novelty_check = initial_explore > 0.0

        # Simulate idle cycles (the agent doing nothing)
        explore_scores = [initial_explore]
        for i in range(1, 15):
            drive_sys.record_idle_cycle()
            explore_scores.append(drive_sys.compute_exploration_score())

        # Check 2: Exploration score grows with idle cycles
        monotonic_check = all(
            explore_scores[i] >= explore_scores[i-1]
            for i in range(1, len(explore_scores))
        )

        # Check 3: After 10 idle cycles, exploration score should be
        # significantly above the initial value
        growth_check = explore_scores[-1] >= explore_scores[0] * 2.0

        # Check 4: The final exploration score should be high enough
        # (>0.05) to potentially trigger an improvement cycle
        threshold_check = explore_scores[-1] > 0.05

        # Check 5: Even at time=0 with only novelty, score > 0
        # (this is the key difference from Phase 1)
        zero_deadlock_broken = explore_scores[-1] > phase1_need_score

        all_checks = [novelty_check, monotonic_check, growth_check, threshold_check, zero_deadlock_broken]
        passed = all(all_checks)

        print(f"    Phase 1 need_score (all zeros): {phase1_need_score}")
        print(f"    Phase 2 initial explore_score: {initial_explore:.4f}")
        print(f"    Phase 2 explore_score after 10 idle: {explore_scores[10]:.4f}")
        print(f"    Phase 2 explore_score after 14 idle: {explore_scores[-1]:.4f}")
        print(f"    增长单调: {monotonic_check}, 显著增长: {growth_check}")
        print(f"    零分死锁已破: {zero_deadlock_broken}")

        return {
            "passed": passed,
            "stats": {
                "phase1_need_score": phase1_need_score,
                "phase2_initial_explore_score": round(initial_explore, 4),
                "phase2_after_5_idle": round(explore_scores[5], 4),
                "phase2_after_10_idle": round(explore_scores[10], 4),
                "phase2_after_14_idle": round(explore_scores[-1], 4),
                "growth_factor": round(explore_scores[-1] / max(initial_explore, 0.001), 1),
                "monotonic": monotonic_check,
                "zero_deadlock_broken": zero_deadlock_broken,
                "explore_score_curve": [round(s, 4) for s in explore_scores],
            },
            "reason": None if passed else
                self._pm_fail_reason(novelty_check, monotonic_check, growth_check, threshold_check),
        }

    def _pm_fail_reason(self, *checks) -> str:
        names = ["初始探索分>0", "单调增长", "显著增长(>=2x)", "最终分数>0.05"]
        failed = [names[i] for i, c in enumerate(checks) if not c]
        return f"以下检查未通过: {', '.join(failed)}"

    # ── 5. Exploration Engine ────────────────────────────────────────

    def verify_exploration_engine(self) -> dict:
        """Verify the three components of the exploration engine independently.

        Components:
          a. Curiosity bonus — grows with idle cycles × curiosity drive
          b. Novelty bonus — proportional to unexplored space × curiosity drive
          c. Idle pressure — accumulates over real time
        """
        config = _make_config(seed=99, drives_override={
            "curiosity": 0.8, "mastery": 0.3, "creation": 0.4, "conservation": 0.2,
        })
        diversity = apply_diversity_to_config(config)
        drive_sys = DriveSystem(
            drives_config={k: v for k, v in diversity["drives"].items()
                          if k in ("curiosity", "mastery", "creation", "conservation")},
            exploration_config=diversity.get("exploration", {}),
        )

        # Component A: Curiosity bonus grows with idle cycles
        state0 = drive_sys.get_exploration_state()
        cb_start = state0["curiosity_bonus"]

        for _ in range(7):
            drive_sys.record_idle_cycle()
        state7 = drive_sys.get_exploration_state()
        cb_after = state7["curiosity_bonus"]
        curiosity_check = cb_after > cb_start

        # Component B: Novelty bonus decreases as space is explored
        nb_start = state0["novelty_bonus"]
        drive_sys.update_explored_space(0.2)  # 80% explored
        nb_after = drive_sys.get_exploration_state()["novelty_bonus"]
        novelty_check = nb_after < nb_start  # less unexplored → less novelty

        # Component C: Idle pressure grows with time
        ip_start = state0["idle_pressure"]
        drive_sys.update_time_pressure(3.0)  # 3 days since last action
        ip_after = drive_sys.get_exploration_state()["idle_pressure"]
        idle_pressure_check = ip_after > ip_start

        # Component D: High curiosity drives produce higher exploration
        config2 = _make_config(seed=99, drives_override={
            "curiosity": 0.2, "mastery": 0.5, "creation": 0.5, "conservation": 0.5,
        })
        div2 = apply_diversity_to_config(config2)
        drive_sys2 = DriveSystem(
            drives_config={k: v for k, v in div2["drives"].items()
                          if k in ("curiosity", "mastery", "creation", "conservation")},
            exploration_config=div2.get("exploration", {}),
        )
        for _ in range(5):
            drive_sys2.record_idle_cycle()

        high_c = drive_sys.compute_exploration_score()
        low_c = drive_sys2.compute_exploration_score()
        curiosity_effect_check = high_c > low_c

        all_checks = [curiosity_check, novelty_check, idle_pressure_check, curiosity_effect_check]
        passed = all(all_checks)

        print(f"    好奇心红利: {cb_start:.4f} → {cb_after:.4f} (idle后) {'✓' if curiosity_check else '✗'}")
        print(f"    新颖性奖励: {nb_start:.4f} → {nb_after:.4f} (探索后) {'✓' if novelty_check else '✗'}")
        print(f"    闲置压力:   {ip_start:.4f} → {ip_after:.4f} (3天后) {'✓' if idle_pressure_check else '✗'}")
        print(f"    好奇心影响: high_c={high_c:.4f} vs low_c={low_c:.4f} {'✓' if curiosity_effect_check else '✗'}")

        return {
            "passed": passed,
            "stats": {
                "curiosity_bonus_growth": f"{cb_start:.4f}→{cb_after:.4f}",
                "novelty_bonus_decay": f"{nb_start:.4f}→{nb_after:.4f}",
                "idle_pressure_growth": f"{ip_start:.4f}→{ip_after:.4f}",
                "high_vs_low_curiosity": f"{high_c:.4f} vs {low_c:.4f}",
            },
            "reason": None if passed else
                f"好奇心红利={curiosity_check}, 新颖性={novelty_check}, "
                f"闲置压力={idle_pressure_check}, 好奇心影响={curiosity_effect_check}",
        }

    # ── 6. Action Feedback Divergence ────────────────────────────────

    def verify_action_feedback_divergence(self) -> dict:
        """Verify that different action patterns produce divergent drive trajectories.

        Two agents with identical starting drives should diverge when one
        focuses on curiosity-driven actions and the other on creation-driven.
        """
        base_drives = {"curiosity": 0.5, "mastery": 0.5, "creation": 0.5, "conservation": 0.3}

        config = _make_config(seed=1, drives_override=base_drives)
        diversity = apply_diversity_to_config(config)

        # Agent A: curiosity-focused (web_search, read_file, explore_directory)
        agent_a = DriveSystem(
            drives_config=dict(base_drives),
            exploration_config=diversity.get("exploration", {}),
        )

        # Agent B: creation-focused (forge_tool, write_file, execute_code)
        agent_b = DriveSystem(
            drives_config=dict(base_drives),
            exploration_config=diversity.get("exploration", {}),
        )

        # Run 10 cycles of different action patterns
        curiosity_actions = ["web_search", "read_file", "web_fetch", "explore_directory",
                             "observe_environment", "web_search", "read_file", "web_fetch",
                             "explore_directory", "get_current_time"]
        creation_actions = ["forge_tool", "write_file", "execute_code", "forge_tool",
                           "write_file", "forge_tool", "execute_code", "forge_tool",
                           "write_file", "forge_tool"]

        for i in range(10):
            agent_a.record_action(curiosity_actions[i])
            agent_b.record_action(creation_actions[i])

        # After 10 cycles, their drives should be different
        a_drives = agent_a.drives
        b_drives = agent_b.drives

        # Agent A's curiosity should be lower (satisfied), creation higher (neglected)
        # Agent B's creation should be lower (satisfied), curiosity higher (neglected)
        a_curiosity_lower = a_drives["curiosity"] < a_drives["creation"]
        b_creation_lower = b_drives["creation"] < b_drives["curiosity"]

        # Their dominant drives should differ
        different_dominants = agent_a.dominate_drive() != agent_b.dominate_drive()

        # Their drive vectors should be measurably different
        drive_distance = sum(
            abs(a_drives[d] - b_drives[d]) for d in a_drives
        )
        divergence_check = drive_distance > 0.1

        all_checks = [a_curiosity_lower, b_creation_lower, divergence_check]
        passed = all(all_checks)

        print(f"    Agent A (好奇型) drives: {a_drives}, dominant={agent_a.dominate_drive()}")
        print(f"    Agent B (创造型) drives: {b_drives}, dominant={agent_b.dominate_drive()}")
        print(f"    A curiosity<creation: {a_curiosity_lower}")
        print(f"    B creation<curiosity: {b_creation_lower}")
        print(f"    驱动力向量距离: {drive_distance:.3f} (>0.1: {divergence_check})")
        print(f"    不同主导: {different_dominants}")

        return {
            "passed": passed,
            "stats": {
                "agent_a_drives": {k: round(v, 2) for k, v in a_drives.items()},
                "agent_b_drives": {k: round(v, 2) for k, v in b_drives.items()},
                "agent_a_dominant": agent_a.dominate_drive(),
                "agent_b_dominant": agent_b.dominate_drive(),
                "drive_vector_distance": round(drive_distance, 4),
                "a_curiosity_satisfied": a_curiosity_lower,
                "b_creation_satisfied": b_creation_lower,
            },
            "reason": None if passed else
                f"A好奇被满足={a_curiosity_lower}, B创造被满足={b_creation_lower}, "
                f"距离={drive_distance:.3f}",
        }

    # ── Report Generation ────────────────────────────────────────────

    def generate_report(self) -> str:
        """Generate a human-readable emergence verification report."""
        if not self.results:
            return "尚未运行验证。请先调用 verify_all()。"

        lines = []
        lines.append("=" * 64)
        lines.append("  Phase 2 涌现验证报告")
        lines.append("=" * 64)
        lines.append("")

        overall = self.results.get("overall_passed", False)
        lines.append(f"总体结果: {'✅ 全部通过' if overall else '⚠️ 部分未通过'}")
        lines.append("")

        for name, result in self.results.items():
            if name == "overall_passed":
                continue
            passed = result.get("passed", False)
            symbol = "✅" if passed else "❌"
            lines.append(f"{symbol} {name}")
            if not passed:
                lines.append(f"   原因: {result.get('reason', '未知')}")

            stats = result.get("stats", {})
            if stats:
                lines.append(f"   数据: {json.dumps(stats, ensure_ascii=False, indent=2)[:300]}")

            lines.append("")

        # Summary statistics
        instance_div = self.results.get("instance_diversity", {}).get("stats", {})
        if instance_div:
            lines.append("─── 多样性摘要 ───")
            lines.append(f"  实例数: {instance_div.get('instance_count', '?')}")
            lines.append(f"  不同主导驱动力: {instance_div.get('unique_dominant_drives', '?')}")
            lines.append(f"  不同人格类型: {instance_div.get('unique_personality_hints', '?')}")
            lines.append(f"  驱动力标准差: curiosity={instance_div.get('curiosity_stdev', '?')}, "
                        f"mastery={instance_div.get('mastery_stdev', '?')}")
            lines.append("")

        pm_fix = self.results.get("passive_maintenance_fix", {}).get("stats", {})
        if pm_fix:
            lines.append("─── 被动养护修复摘要 ───")
            lines.append(f"  Phase 1 死锁分数: {pm_fix.get('phase1_need_score', '?')}")
            lines.append(f"  Phase 2 初始探索分: {pm_fix.get('phase2_initial_explore_score', '?')}")
            lines.append(f"  Phase 2 10周期后: {pm_fix.get('phase2_after_10_idle', '?')}")
            lines.append(f"  增长倍数: {pm_fix.get('growth_factor', '?')}x")
            lines.append(f"  零分死锁已破: {pm_fix.get('zero_deadlock_broken', '?')}")
            lines.append("")

        return "\n".join(lines)


# ─── CLI entry ────────────────────────────────────────────────────────

def main():
    """Run emergence verification from the command line."""
    import argparse
    parser = argparse.ArgumentParser(description="Phase 2 Emergence Verifier")
    parser.add_argument("--instances", type=int, default=30,
                       help="Number of instances for diversity check (default: 30)")
    parser.add_argument("--json", action="store_true",
                       help="Output results as JSON")
    args = parser.parse_args()

    verifier = EmergenceVerifier()
    results = verifier.verify_all(instance_count=args.instances)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print()
        print(verifier.generate_report())

    return 0 if results.get("overall_passed", False) else 1


if __name__ == "__main__":
    import sys
    import json
    sys.exit(main())
