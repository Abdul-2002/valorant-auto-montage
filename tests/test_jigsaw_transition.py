import tempfile
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.ai.engine.transition_planner import plan_transitions, scene_jigsaw_slots
from src.effects.transitions.jigsaw import (
    PIECE_TRAVEL_SEC,
    REST_LABEL,
    WEAPON_LABEL,
    build_pieces,
    entry_offset,
    fixed_piece_labels,
    jigsaw_tail_frame,
    load_piece_labels,
    piece_starts,
    style_jigsaw_tail,
)
from src.effects.transitions.motion_style import style_pop_slam_head
from src.pipeline.jigsaw_assets import MAX_SEGMENTS, compose_piece_labels, gun_zone_segment, pick_scene_segments
from src.pipeline.weapon_assets import weapon_mask_at

H, W = 90, 160
OUT_RGB = (200, 30, 30)
IN_RGB = (20, 40, 220)


class _FakeClip:
    def __init__(self, frames: list[np.ndarray], fps: float = 30.0):
        self._frames = frames
        self.fps = fps
        self.duration = len(frames) / fps

    def transform(self, fn):
        out = []
        for i, fr in enumerate(self._frames):
            t = i / self.fps
            out.append(fn(lambda _t, f=fr: f, t))
        return _FakeClip(out, self.fps)


def _solid(rgb: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[:, :] = rgb
    return frame


def _box(x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    mask = np.zeros((H, W), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask


def test_pop_slam_head_preserves_shape() -> None:
    frame = np.random.randint(0, 255, (90, 160, 3), dtype=np.uint8)
    clip = _FakeClip([frame.copy() for _ in range(10)])
    styled = style_pop_slam_head(clip, duration_sec=0.15)
    assert styled._frames[0].shape == frame.shape


def test_should_put_gun_bottom_right_and_rest_centre_when_using_fixed_layout() -> None:
    labels = fixed_piece_labels(H, W)
    assert labels[H - 1, int(0.7 * W)] == WEAPON_LABEL
    assert labels[H // 2, W // 2] == REST_LABEL
    assert {int(v) for v in np.unique(labels)} == {0, 1, 2, 3, 4}


def test_should_fall_back_to_fixed_layout_when_piece_map_missing() -> None:
    fixed = fixed_piece_labels(H, W)
    assert np.array_equal(load_piece_labels(None, W, H), fixed)
    assert np.array_equal(load_piece_labels(str(Path(tempfile.gettempdir()) / "no_such_map.png"), W, H), fixed)


def test_should_resize_baked_piece_map_with_nearest_labels_when_size_differs() -> None:
    small = np.zeros((H // 2, W // 2), dtype=np.uint8)
    small[:, W // 4 :] = 3
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "pieces.png")
        cv2.imwrite(path, small)
        labels = load_piece_labels(path, W, H)
    assert labels.shape == (H, W)
    assert {int(v) for v in np.unique(labels)} == {0, 3}


def test_should_return_2d_labels_when_imread_yields_singleton_channel() -> None:
    labels = fixed_piece_labels(H, W)
    original = cv2.imread
    cv2.imread = lambda *_a, **_k: labels[..., None]
    try:
        loaded = load_piece_labels("patched.png", W, H)
    finally:
        cv2.imread = original
    assert loaded.shape == (H, W)
    assert np.array_equal(loaded, labels)


def test_should_enter_from_bottom_for_gun_and_nearest_edge_otherwise() -> None:
    gun = _box(90, 60, 140, 90)
    assert entry_offset(gun, from_bottom=True) == (0.0, float(H - 60))
    left = _box(0, 20, 30, 70)
    assert entry_offset(left, from_bottom=False) == (-30.0, 0.0)
    top = _box(50, 0, 110, 12)
    assert entry_offset(top, from_bottom=False) == (0.0, -12.0)


def test_should_land_events_on_eighth_notes_with_rest_on_the_cut() -> None:
    starts = piece_starts(4, beat_sec=0.4, max_tail_sec=2.0)
    assert np.allclose(np.diff(starts), 0.2)
    assert abs(starts[-1] + PIECE_TRAVEL_SEC) < 1e-9


def test_should_compress_stagger_when_outgoing_tail_is_short() -> None:
    starts = piece_starts(4, beat_sec=0.4, max_tail_sec=0.3)
    assert starts[0] >= -0.3 - 1e-9
    assert starts == sorted(starts)


def test_should_show_gun_before_scene_piece_when_assembling() -> None:
    labels = np.zeros((H, W), dtype=np.uint8)
    labels[_box(90, 60, 140, 90)] = WEAPON_LABEL
    labels[_box(0, 10, 40, 80)] = 2
    frame_a, frame_b = _solid(OUT_RGB), _solid(IN_RGB)
    pieces = build_pieces(frame_b, labels)
    starts = piece_starts(len(pieces) + 1, beat_sec=0.4, max_tail_sec=2.0)
    frame = jigsaw_tail_frame(frame_a, frame_b, pieces, labels == REST_LABEL, starts[1], starts)
    assert not np.array_equal(frame[75, 115], np.array(OUT_RGB, dtype=np.uint8))
    assert tuple(frame[45, 20]) == OUT_RGB
    assert tuple(frame[45, 80]) == OUT_RGB


def test_should_preserve_frames_and_converge_to_incoming_when_styling_tail() -> None:
    labels = fixed_piece_labels(H, W)
    clip = _FakeClip([_solid(OUT_RGB) for _ in range(30)])
    styled = style_jigsaw_tail(clip, incoming_frame=_solid(IN_RGB), labels=labels, beat_sec=0.4)
    assert len(styled._frames) == 30
    assert np.array_equal(styled._frames[0], _solid(OUT_RGB))
    last = styled._frames[-1].astype(np.int16)
    assert float(np.abs(last - np.array(IN_RGB, dtype=np.int16)).mean()) < 8.0


def test_should_pick_scene_jigsaws_off_flash_and_apart_from_other_jigsaws() -> None:
    kinds = ["hard_cut", "push", "flash_white", "hard_cut", "hard_cut", "jigsaw"]
    sources = [(k, 10.0) for k in range(7)]
    assert scene_jigsaw_slots(kinds, sources) == {0, 3}


def test_should_skip_scene_jigsaw_when_next_kill_is_same_round() -> None:
    kinds = ["hard_cut", "hard_cut", "hard_cut", "hard_cut", "jigsaw"]
    sources = [(0, 10.0), (0, 15.0), (0, 80.0), (0, 85.0), (1, 0.0), (2, 0.0)]
    assert scene_jigsaw_slots(kinds, sources) == {1}


def test_should_size_jigsaws_to_one_beat_and_add_scene_jigsaws_only_in_reference_style() -> None:
    sources = [(k, 0.0) for k in range(6)]
    base = plan_transitions(num_clips=6, beat_map=None, flash_frequency=0.0, clip_sources=sources, beat_interval_sec=0.4)
    ref = plan_transitions(
        num_clips=6, beat_map=None, flash_frequency=0.0, clip_sources=sources, scene_jigsaw=True, beat_interval_sec=0.4
    )
    base_kinds = [t.type for t in base.transitions_to_next[:-1]]
    ref_kinds = [t.type for t in ref.transitions_to_next[:-1]]
    assert base_kinds[-1] == "jigsaw"
    assert ref_kinds.count("jigsaw") > base_kinds.count("jigsaw")
    assert all(t.duration_sec == 0.4 for t in ref.transitions_to_next[:-1] if t.type == "jigsaw")


def test_should_never_stack_a_rotation_jigsaw_before_the_finale_jigsaw() -> None:
    chorus = SimpleNamespace(sections=[SimpleNamespace(start_sec=0.0, end_sec=100.0, section_type="chorus")])
    plan = plan_transitions(num_clips=3, beat_map=chorus, flash_frequency=0.0, beat_interval_sec=0.4)
    assert [t.type for t in plan.transitions_to_next[:-1]] == ["pop_slam", "jigsaw"]


def test_should_promote_gun_shaped_segment_in_weapon_box_when_prompt_fails() -> None:
    pistol = _box(100, 60, 130, 80)
    wall = _box(0, 0, 50, 90)
    sky_strip = _box(60, 0, 160, 20)
    gun = gun_zone_segment([wall, sky_strip, pistol])
    assert gun is not None and gun[70, 115] and not gun[45, 20]


def test_should_not_promote_segment_outside_weapon_box() -> None:
    assert gun_zone_segment([_box(10, 60, 40, 80)]) is None
    assert gun_zone_segment([]) is None


class _FakeMaskData:
    def __init__(self, arr: np.ndarray):
        self._arr = arr

    def __len__(self) -> int:
        return len(self._arr)

    def cpu(self):
        return self

    def numpy(self) -> np.ndarray:
        return self._arr


def _fake_sam(masks: np.ndarray) -> SimpleNamespace:
    def predictor(_bgr, *, bboxes, multimask_output):
        out = masks if multimask_output else masks[:1]
        return [SimpleNamespace(masks=SimpleNamespace(data=_FakeMaskData(out)))]

    return SimpleNamespace(predictor=predictor)


def test_should_take_whole_gun_from_multimask_when_top_mask_is_fragment() -> None:
    fragment, gun, huge = _box(110, 64, 116, 68), _box(100, 60, 140, 80), _box(0, 40, 160, 90)
    model = _fake_sam(np.stack([fragment, gun, huge]))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pov.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (W, H))
        for _ in range(10):
            writer.write(_solid((60, 60, 60)))
        writer.release()
        whole = weapon_mask_at(model, path, 0.1, (W, H), multimask=True)
        single = weapon_mask_at(model, path, 0.1, (W, H))
    assert whole is not None and whole[70, 120] and not whole[45, 20]
    assert single is None


def test_should_pick_largest_disjoint_mid_size_segments() -> None:
    weapon = _box(90, 60, 140, 90)
    big = _box(0, 0, 60, 60)
    mid = _box(60, 0, 100, 40)
    tiny = _box(0, 80, 5, 85)
    huge = _box(0, 0, 160, 50)
    on_gun = _box(92, 62, 138, 88)
    chosen = pick_scene_segments([mid, tiny, huge, on_gun, big], weapon)
    assert len(chosen) == 2
    assert chosen[0][30, 30] and chosen[1][20, 80]
    assert not (chosen[0] & chosen[1]).any()


def test_should_cap_scene_segments() -> None:
    strips = [_box(20 * k, 0, 20 * k + 18, 40) for k in range(6)]
    assert len(pick_scene_segments(strips, np.zeros((H, W), dtype=bool))) == MAX_SEGMENTS


def test_should_number_segments_after_gun_and_use_precise_gun_in_fixed_fallback() -> None:
    weapon = _box(95, 65, 135, 90)
    labels = compose_piece_labels(H, W, weapon, [_box(0, 0, 60, 60), _box(60, 0, 100, 40)])
    assert {int(v) for v in np.unique(labels)} == {0, 1, 2, 3}
    assert labels[70, 100] == WEAPON_LABEL
    fallback = compose_piece_labels(H, W, weapon, [])
    assert np.array_equal(fallback == WEAPON_LABEL, weapon)
    assert fallback[H // 2, 5] == 2
