"""
LensYou E2E Dedicated Test Runner
Executes E2E test suites across Tiers 1-4 with tier-filtering and summary reporting.
"""

import sys
import os
import time
import argparse
import unittest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

TIER_MAP = {
    1: ("Tier 1: Feature Coverage", "e2e_tests.test_tier1_features"),
    2: ("Tier 2: Boundary & Corner Cases", "e2e_tests.test_tier2_boundaries"),
    3: ("Tier 3: Cross-Feature Interactions", "e2e_tests.test_tier3_interactions"),
    4: ("Tier 4: Real-World Workflows", "e2e_tests.test_tier4_scenarios"),
}


def run_tier(tier_num: int, verbosity: int = 1):
    tier_name, module_path = TIER_MAP[tier_num]
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(module_path)
    
    print(f"\n{'='*70}")
    print(f"Running {tier_name} ({module_path})")
    print(f"{'='*70}")
    
    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    elapsed = time.time() - start_time
    
    return {
        "tier": tier_num,
        "name": tier_name,
        "total": result.testsRun,
        "passes": result.testsRun - len(result.failures) - len(result.errors),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "elapsed": elapsed,
        "was_successful": result.wasSuccessful()
    }


def main():
    parser = argparse.ArgumentParser(description="LensYou 4-Tier E2E Test Runner")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Run specific tier only")
    parser.add_argument("-v", "--verbose", action="count", default=1, help="Verbosity level")
    args = parser.parse_args()

    tiers_to_run = [args.tier] if args.tier else [1, 2, 3, 4]
    
    print("\n" + "#"*70)
    print(" LensYou Production Upgrade — 4-Tier E2E Test Suite Execution")
    print("#"*70)
    
    results = []
    all_success = True
    
    total_start = time.time()
    for t in tiers_to_run:
        res = run_tier(t, verbosity=args.verbose)
        results.append(res)
        if not res["was_successful"]:
            all_success = False
            
    total_elapsed = time.time() - total_start
    
    # Summary Table
    print("\n" + "="*70)
    print(" E2E TEST EXECUTION SUMMARY")
    print("="*70)
    print(f"{'Tier':<35} | {'Tests':<6} | {'Pass':<5} | {'Fail':<5} | {'Error':<5} | {'Time (s)':<8}")
    print("-" * 75)
    
    total_tests = sum(r["total"] for r in results)
    total_passes = sum(r["passes"] for r in results)
    total_fails = sum(r["failures"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    
    for r in results:
        status_flag = "PASS" if r["was_successful"] else "FAIL"
        print(f"{r['name']:<35} | {r['total']:<6} | {r['passes']:<5} | {r['failures']:<5} | {r['errors']:<5} | {r['elapsed']:<8.2f}")
        
    print("-" * 75)
    print(f"{'TOTAL':<35} | {total_tests:<6} | {total_passes:<5} | {total_fails:<5} | {total_errors:<5} | {total_elapsed:<8.2f}")
    print("="*70)
    
    if all_success:
        print("\n [SUCCESS] ALL E2E TEST TIERS EXECUTED CLEANLY AND PASSED!\n")
        sys.exit(0)
    else:
        print("\n [FAILURE] ONE OR MORE E2E TEST TIERS FAILED.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
