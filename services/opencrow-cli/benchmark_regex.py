import timeit
import re
from urllib.parse import unquote, urlsplit
import importlib.util
import sys

def load_module_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

opencrow_mcp_core = load_module_from_path('opencrow_mcp_core', 'scripts/opencrow_mcp_core.py')

def benchmark_match_uri_template():
    # Setup some test data
    setup_code = """
from __main__ import opencrow_mcp_core
uri_template = "http://example.com/api/{resource_id}/details/{detail_id}"
uri = "http://example.com/api/12345/details/67890"
"""
    stmt = "opencrow_mcp_core.match_uri_template(uri_template, uri)"

    # Run benchmark
    iterations = 100000
    times = timeit.repeat(stmt, setup=setup_code, number=iterations, repeat=5)
    best_time = min(times)
    print(f"Time for {iterations} iterations: {best_time:.4f} seconds")
    print(f"Time per call: {(best_time / iterations) * 1e6:.2f} microseconds")

if __name__ == "__main__":
    print("Baseline Benchmark:")
    benchmark_match_uri_template()
