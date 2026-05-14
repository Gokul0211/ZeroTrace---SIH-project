import os
import sys
import subprocess

# Add the build directory to the path so it can find zerotrace_core.so
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../core/build')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../core')))

try:
    import zerotrace_core
except ImportError as e:
    print(f"Failed to import zerotrace_core: {e}")
    print("Ensure you have built the C++ core engine using CMake first!")
    sys.exit(1)

print("--- Test 1: Entropy of a zero-filled buffer ---")
# Create a 10MB zero file and test
subprocess.run(["dd", "if=/dev/zero", "of=/tmp/test_zero.img", "bs=1M", "count=10"], capture_output=True)
result = zerotrace_core.analyze_entropy("/tmp/test_zero.img", zerotrace_core.WipeMode.CLEAR)
print(f"Zero entropy: {result.entropy_bits:.4f} — verified: {result.wipe_verified} (state: {result.state})")
# Expected: ~0.0, verified=True

print("\n--- Test 2: Entropy of random data ---")
subprocess.run(["dd", "if=/dev/urandom", "of=/tmp/test_random.img", "bs=1M", "count=10"], capture_output=True)
result = zerotrace_core.analyze_entropy("/tmp/test_random.img", zerotrace_core.WipeMode.PURGE)
print(f"Random entropy: {result.entropy_bits:.4f} — verified: {result.wipe_verified} (state: {result.state})")
# Expected: ~7.99, verified=True

# Cleanup
try:
    os.remove("/tmp/test_zero.img")
    os.remove("/tmp/test_random.img")
except FileNotFoundError:
    pass
