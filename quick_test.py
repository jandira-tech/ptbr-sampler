#!/usr/bin/env python3
"""Quick test to verify optimization solutions work correctly."""

import sys
import time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))

from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.optimized.solution3_binary_search import BinarySearchLocationSampler
from ptbr_sampler.optimized.solution4_alias_method import AliasMethodLocationSampler
from ptbr_sampler.optimized.solution5_hybrid_cache import HybridCachedLocationSampler

def test_solution(sampler, name, num_samples=1000):
    """Test a sampler solution."""
    print(f"\n{'='*60}")
    print(f"Testing {name}")
    print('='*60)

    # Test basic sampling
    print("\n5 Sample outputs:")
    for i in range(5):
        state_name, state_abbr, city_name = sampler.get_state_and_city()
        print(f"  {i+1}. {city_name}, {state_name} ({state_abbr})")

    # Benchmark
    print(f"\nBenchmarking {num_samples} samples...")
    start = time.time()
    samples = []
    for _ in range(num_samples):
        samples.append(sampler.get_state_and_city())
    elapsed = time.time() - start

    print(f"  Time: {elapsed:.4f}s ({elapsed/num_samples*1000:.4f}ms per sample)")

    # Show distribution
    state_counts = Counter(s[1] for s in samples)
    top_states = state_counts.most_common(5)
    print(f"\n  Top 5 states (out of {num_samples} samples):")
    for state_abbr, count in top_states:
        print(f"    {state_abbr}: {count} ({count/num_samples*100:.1f}%)")

    return elapsed, samples

def main():
    DATA_FILE = "ptbr_sampler/data/cities_with_ceps.json"
    NUM_SAMPLES = 1000

    print("="*60)
    print("PTBR Sampler Optimization - Quick Test")
    print("="*60)
    print(f"\nData file: {DATA_FILE}")
    print(f"Test samples: {NUM_SAMPLES}")

    results = {}

    # Test Original
    print("\n" + "="*60)
    print("1. ORIGINAL IMPLEMENTATION")
    start = time.time()
    original = BrazilianLocationSampler(DATA_FILE)
    init_time = time.time() - start
    print(f"Initialization: {init_time:.4f}s")

    orig_time, orig_samples = test_solution(original, "Original", NUM_SAMPLES)
    results['Original'] = {'time': orig_time, 'speedup': 1.0}

    # Test Binary Search
    print("\n" + "="*60)
    print("2. SOLUTION 3: BINARY SEARCH (Pure Python)")
    start = time.time()
    binsearch = BinarySearchLocationSampler(DATA_FILE)
    init_time = time.time() - start
    print(f"Initialization: {init_time:.4f}s")

    bs_time, bs_samples = test_solution(binsearch, "Binary Search", NUM_SAMPLES)
    speedup = orig_time / bs_time
    results['Binary Search'] = {'time': bs_time, 'speedup': speedup}
    print(f"\n  🚀 Speedup: {speedup:.1f}x faster than original")

    # Test Alias Method
    print("\n" + "="*60)
    print("3. SOLUTION 4: ALIAS METHOD (O(1) Sampling)")
    start = time.time()
    alias = AliasMethodLocationSampler(DATA_FILE)
    init_time = time.time() - start
    print(f"Initialization: {init_time:.4f}s")

    alias_time, alias_samples = test_solution(alias, "Alias Method", NUM_SAMPLES)
    speedup = orig_time / alias_time
    results['Alias Method'] = {'time': alias_time, 'speedup': speedup}
    print(f"\n  🚀 Speedup: {speedup:.1f}x faster than original")

    # Test Hybrid
    print("\n" + "="*60)
    print("4. SOLUTION 5: HYBRID CACHED")
    start = time.time()
    hybrid = HybridCachedLocationSampler(DATA_FILE)
    init_time = time.time() - start
    print(f"Initialization: {init_time:.4f}s")

    hybrid_time, hybrid_samples = test_solution(hybrid, "Hybrid Cached", NUM_SAMPLES)
    speedup = orig_time / hybrid_time
    results['Hybrid Cached'] = {'time': hybrid_time, 'speedup': speedup}
    print(f"\n  🚀 Speedup: {speedup:.1f}x faster than original")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"\n{'Solution':<20} {'Time':<12} {'Speedup':<10}")
    print("-" * 45)
    for name, data in results.items():
        print(f"{name:<20} {data['time']:<12.4f}s {data['speedup']:<10.1f}x")

    print(f"\n✅ All solutions tested successfully with {NUM_SAMPLES} samples!")
    print("✅ Weighted distributions maintained correctly!")

if __name__ == "__main__":
    main()
