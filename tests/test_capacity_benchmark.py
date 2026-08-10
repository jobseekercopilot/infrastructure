import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


capacity = load_module("capacity_run", "scripts/benchmark/run_capacity.py")
reporting = load_module("capacity_report", "scripts/benchmark/generate_report.py")
prepare_demo = load_module("prepare_demo", "scripts/demo/prepare_demo.py")


class CapacityBenchmarkTest(unittest.TestCase):
    def test_demo_summary_is_optional_when_dataset_lives_in_runtime_image(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(prepare_demo, "dataset_path", return_value=Path(directory)):
                self.assertEqual(
                    prepare_demo.dataset_summary(),
                    {
                        "available": False,
                        "jobCount": None,
                        "locationCount": None,
                        "providers": {},
                    },
                )

    def test_docker_sizes_and_percentiles_are_deterministic(self):
        self.assertEqual(capacity.parse_size("1.5MiB"), 1572864)
        self.assertEqual(capacity.parse_pair("1.5MB / 2GB"), (1500000, 2000000000))
        self.assertEqual(capacity.percentile([10, 20, 30, 40], 0.50), 20)
        self.assertEqual(capacity.percentile([10, 20, 30, 40], 0.95), 40)
        self.assertIsNone(capacity.percentile([], 0.99))

    def test_summary_keeps_per_service_and_aggregate_measurements_separate(self):
        samples = [
            {"containers": [
                {"container": "service-a", "cpuPercent": 1.0, "memoryUsedBytes": 100,
                 "networkRxBytes": 10, "networkTxBytes": 20, "blockReadBytes": 30, "blockWriteBytes": 40},
                {"container": "service-b", "cpuPercent": 2.0, "memoryUsedBytes": 200,
                 "networkRxBytes": 11, "networkTxBytes": 21, "blockReadBytes": 31, "blockWriteBytes": 41},
            ]},
            {"containers": [
                {"container": "service-a", "cpuPercent": 3.0, "memoryUsedBytes": 150,
                 "networkRxBytes": 12, "networkTxBytes": 22, "blockReadBytes": 32, "blockWriteBytes": 42},
                {"container": "service-b", "cpuPercent": 4.0, "memoryUsedBytes": 250,
                 "networkRxBytes": 13, "networkTxBytes": 23, "blockReadBytes": 33, "blockWriteBytes": 43},
            ]},
        ]
        inspection = [{"container": "service-a", "restartCount": 0, "oomKilled": False,
                       "status": "running", "health": "healthy"}]
        summary = capacity.summarise(samples, inspection)
        self.assertEqual(summary["aggregate"]["memoryBytesIdle"], 300)
        self.assertEqual(summary["aggregate"]["memoryBytesPeak"], 400)
        self.assertEqual(summary["services"]["service-a"]["cpuPercentPeak"], 3.0)
        self.assertEqual(summary["oomKilledContainers"], [])

    def test_report_rejects_non_measured_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            output = Path(directory) / "report.md"
            source.write_text(json.dumps({"schemaVersion": 1, "evidenceClass": "projected"}))
            with self.assertRaises(SystemExit):
                original = __import__("sys").argv
                try:
                    __import__("sys").argv = ["generate_report.py", str(source), "--output", str(output)]
                    reporting.main()
                finally:
                    __import__("sys").argv = original


if __name__ == "__main__":
    unittest.main()
