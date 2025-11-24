# Run the sweep test
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --min-rate 5 \
    --max-rate 30 \
    --rate-step 5 \
    --duration 90

echo ""
echo "Sweep test completed!"
echo "Results saved to sequential_load_test_sweep_results_*.json"