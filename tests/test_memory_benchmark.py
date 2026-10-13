from pathlib import Path
import runpy
import unittest


class MemoryBenchmarkTests(unittest.TestCase):
    def test_small_real_markdown_corpus_passes_correctness_gate(self):
        module = runpy.run_path(str(Path(__file__).parents[1] / "benchmarks" / "memory_markdown_benchmark.py"))
        result = module["run_benchmark"](100)
        self.assertTrue(all(result["checks"].values()), result)
        self.assertEqual(result["notes"], 100)


if __name__ == "__main__":
    unittest.main()
