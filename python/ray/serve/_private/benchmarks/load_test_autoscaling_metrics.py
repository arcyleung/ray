import asyncio
import os

import ray
from ray import serve


@serve.deployment(
    autoscaling_config={
        "min_replicas": 50,
        "max_replicas": 300,
        "target_num_ongoing_requests_per_replica": 1,
        "upscale_delay_s": 2,
        "downscale_delay_s": 10,
    },
    name="load_test",
    ray_actor_options={"num_cpus": 0.01},
)
class LoadTestDeployment:
    def __call__(self):
        # The work here is minimal, the goal is just to have many
        # replicas that are alive and reporting metrics.
        pass


async def main():
    """
    Deploys the application and sends requests to it continuously.
    """
    os.environ["RAY_SERVE_COLLECT_AUTOSCALING_METRICS_ON_HANDLE"] = "0"
    ray.init(
        address="local",
        namespace="serve",
        num_cpus=8,
        _temp_dir="/home/arcyleung/ray",
        _metrics_export_port=9999,
        _system_config={
            "metrics_report_interval_ms": 100,
            "task_retry_delay_ms": 50,
        },
    )
    handle = serve.run(LoadTestDeployment.bind())

    print("Deployment is running. Sending requests to generate load...")

    while True:
        # Send requests in a loop to trigger the replicas' metric reporting.
        handles = [handle.remote() for _ in range(40)]
        await asyncio.gather(*handles)
        await asyncio.sleep(0.5)

        # metrics = fetch_prometheus_metrics(["localhost:9999"])

        # print(f"Metrics: {metrics}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Test finished. Shutting down Serve.")
        serve.shutdown()
