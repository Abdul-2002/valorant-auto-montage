import numpy as np

from src.effects.color_grading import _grade_frame_cpu, _grade_frame_cuda


def test_should_match_opencv_color_grade_on_cuda() -> None:
    frame = np.random.default_rng(0).integers(0, 256, (48, 80, 3), dtype=np.uint8)
    cpu = _grade_frame_cpu(frame, 1.1, 0.02, 1.3)
    gpu = _grade_frame_cuda(frame, 1.1, 0.02, 1.3)
    assert int(np.abs(cpu.astype(np.int16) - gpu.astype(np.int16)).max()) <= 1
