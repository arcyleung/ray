# Run the sweep test 5 times to obtain averages
echo "Running sweep test 5 times to obtain average results..."
echo ""

# Create a directory to store results if it doesn't exist
mkdir -p sweep_results

# Run the test 5 times
for i in {1..3}; do
    echo "Running test iteration $i/5..."
    python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
        --min-rate 5 \
        --max-rate 20 \
        --rate-step 5 \
        --duration 60

    latest_file=$(ls -t sequential_load_test_sweep_results_*.json | head -n1)
    if [ -n "$latest_file" ]; then
        mv "$latest_file" "sweep_results/iteration_${i}_$(basename $latest_file)"
        echo "  Results saved to sweep_results/iteration_${i}_$(basename $latest_file)"
    fi

    echo "  Iteration $i completed"
    echo ""
done

echo "All 5 iterations completed!"
echo "Results saved in sweep_results/ directory"
echo "Run plot_autoscaling_comparison.py to generate boxplots with quartiles"