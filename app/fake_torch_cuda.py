# Fake CUDA module to bypass import errors in PyTorch (CPU-only)
class _FakeCuda:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

is_available = False
device_count = 0
current_device = 0
get_device_name = lambda *args, **kwargs: "CPU"
