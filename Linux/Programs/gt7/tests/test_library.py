"""Saved circuits and recognising which one is being driven."""

from __future__ import annotations

import math

import pytest

from gt7.library import (
    MATCH_HOLD,
    TrackLibrary,
    default_path,
    downsample,
)


def circle(radius: float, n: int, cx: float = 0.0, cz: float = 0.0):
    xs, zs, inputs = [], [], []
    for i in range(n):
        angle = 2 * math.pi * i / n
        xs.append(cx + radius * math.cos(angle))
        zs.append(cz + radius * math.sin(angle))
        inputs.append(2)
    return xs, zs, inputs


@pytest.fixture
def library(tmp_path) -> TrackLibrary:
    return TrackLibrary(tmp_path / "tracks.json", autoload=False)


def test_a_completed_lap_is_saved(library):
    xs, zs, inputs = circle(300.0, 400)
    saved = library.remember(xs, zs, inputs, 2 * math.pi * 300)
    assert saved is not None
    assert saved.length == pytest.approx(1885, rel=0.01)
    assert len(library.tracks) == 1
    assert library.path.exists()


def test_a_scrap_of_a_lap_is_not_saved(library):
    xs, zs, inputs = circle(300.0, 6)
    assert library.remember(xs, zs, inputs, 40.0) is None
    assert library.tracks == []


def test_driving_a_saved_circuit_recognises_it(library):
    xs, zs, inputs = circle(300.0, 400)
    saved = library.remember(xs, zs, inputs, 2 * math.pi * 300)
    library.active_id = None

    matched = None
    for _ in range(MATCH_HOLD):
        matched = library.update_match(xs[:150], zs[:150])
    assert matched is not None
    assert matched.id == saved.id


def test_a_different_circuit_is_not_confused_for_a_saved_one(library):
    a = circle(300.0, 400)
    b = circle(500.0, 500, cx=20_000, cz=20_000)
    library.remember(*a, 2 * math.pi * 300)
    library.remember(*b, 2 * math.pi * 500)

    for _ in range(MATCH_HOLD):
        matched = library.update_match(b[0][:150], b[1][:150])
    assert matched is not None
    assert matched.length == pytest.approx(2 * math.pi * 500, rel=0.01)


def test_unknown_ground_matches_nothing(library):
    xs, zs, inputs = circle(300.0, 400)
    library.remember(xs, zs, inputs, 2 * math.pi * 300)
    # remember() leaves that circuit selected - you are, after all, on it.
    # Clear it so this tests recognition from cold, not the drop hysteresis.
    library.active_id = None
    far_x, far_z, _ = circle(200.0, 300, cx=-90_000, cz=-90_000)
    assert library.update_match(far_x[:150], far_z[:150]) is None


def test_one_stray_reading_does_not_switch_circuits(library):
    """Hysteresis: a pit lane crossing must not flip the map mid-corner."""
    a = circle(300.0, 400)
    b = circle(500.0, 500, cx=20_000, cz=20_000)
    library.remember(*a, 2 * math.pi * 300)
    library.remember(*b, 2 * math.pi * 500)

    for _ in range(MATCH_HOLD):
        library.update_match(a[0][:150], a[1][:150])
    settled = library.active_id

    library.update_match(b[0][:150], b[1][:150])   # a single stray check
    assert library.active_id == settled


def test_losing_the_track_takes_more_than_losing_it_once(library):
    xs, zs, inputs = circle(300.0, 400)
    library.remember(xs, zs, inputs, 2 * math.pi * 300)
    for _ in range(MATCH_HOLD):
        library.update_match(xs[:150], zs[:150])
    assert library.active_id is not None

    far_x, far_z, _ = circle(200.0, 300, cx=-90_000, cz=-90_000)
    library.update_match(far_x[:150], far_z[:150])
    assert library.active_id is not None            # one bad check is not enough
    for _ in range(MATCH_HOLD * 2):
        library.update_match(far_x[:150], far_z[:150])
    assert library.active_id is None


def test_redriving_refreshes_instead_of_duplicating(library):
    xs, zs, inputs = circle(300.0, 400)
    first = library.remember(xs, zs, inputs, 2 * math.pi * 300)
    again = library.remember(xs, zs, inputs, 2 * math.pi * 300)
    assert len(library.tracks) == 1
    assert again.id == first.id
    assert again.laps_seen == 2


def shortcut(radius: float, n: int, keep: float = 0.35):
    """Most of the circle, then a chord straight back to the start.

    A genuinely shorter *layout* over shared roads - not a fragment, which the
    loop test would rightly refuse to save at all. It has to be well clear of
    LENGTH_TOLERANCE too, or treating it as the same circuit is correct.
    """
    kept = int(n * keep)
    xs, zs, inputs = [], [], []
    for i in range(kept):
        angle = 2 * math.pi * i / n
        xs.append(radius * math.cos(angle))
        zs.append(radius * math.sin(angle))
        inputs.append(2)
    for i in range(1, 40):                      # chord home
        t = i / 40
        xs.append(xs[kept - 1] + (radius - xs[kept - 1]) * t)
        zs.append(zs[kept - 1] * (1 - t))
        inputs.append(2)
    return xs, zs, inputs


def path_length(xs, zs):
    return sum(math.dist((xs[i - 1], zs[i - 1]), (xs[i], zs[i]))
               for i in range(1, len(xs)))


def test_a_shorter_layout_sharing_a_route_is_kept_separate(library):
    """Overlap alone is not identity - a short layout is its own circuit."""
    xs, zs, inputs = circle(300.0, 400)
    library.remember(xs, zs, inputs, 2 * math.pi * 300)
    short = shortcut(300.0, 400)
    library.remember(*short, path_length(short[0], short[1]))
    assert len(library.tracks) == 2


def test_rename_and_forget(library):
    xs, zs, inputs = circle(300.0, 400)
    saved = library.remember(xs, zs, inputs, 2 * math.pi * 300)
    assert library.rename(saved.id, "  Brands Hatch  ").name == "Brands Hatch"
    assert library.rename("nope", "x") is None

    assert library.forget(saved.id) is True
    assert library.tracks == []
    assert library.active_id is None
    assert library.forget(saved.id) is False


def test_library_survives_a_restart(tmp_path):
    path = tmp_path / "tracks.json"
    first = TrackLibrary(path, autoload=False)
    xs, zs, inputs = circle(300.0, 400)
    first.remember(xs, zs, inputs, 2 * math.pi * 300)
    first.rename(first.tracks[0].id, "Suzuka")

    second = TrackLibrary(path)
    assert [t.name for t in second.tracks] == ["Suzuka"]
    for _ in range(MATCH_HOLD):
        matched = second.update_match(xs[:150], zs[:150])
    assert matched is not None and matched.name == "Suzuka"


def test_a_corrupt_library_does_not_crash_startup(tmp_path):
    path = tmp_path / "tracks.json"
    path.write_text("{ this is not json")
    assert TrackLibrary(path).tracks == []


def test_a_bad_row_does_not_lose_the_whole_file(tmp_path):
    import json

    xs, zs, inputs = circle(300.0, 200)
    good = {"id": "a", "name": "Good", "length": 2 * math.pi * 300,
            "points": [[round(x, 1), round(z, 1), 2] for x, z, in zip(xs, zs)],
            "bbox": [-300, -300, 300, 300], "created": 1.0}
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps([good, {"broken": True}]))
    assert [t.name for t in TrackLibrary(path).tracks] == ["Good"]


def test_downsample_thins_without_losing_the_shape():
    xs, zs, inputs = circle(300.0, 2000)
    points = downsample(xs, zs, inputs, spacing=6.0)
    assert len(points) < len(xs) / 3
    assert len(points) > 200          # still enough to draw a circle


def test_default_path_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_path() == tmp_path / "gt7" / "tracks.json"


def test_two_laps_saved_in_the_same_millisecond_get_distinct_ids(library):
    """A colliding id makes by_id() return the wrong circuit entirely."""
    a = circle(300.0, 400)
    b = circle(500.0, 500, cx=20_000, cz=20_000)
    first = library.remember(*a, 2 * math.pi * 300, now=1000.0)
    second = library.remember(*b, 2 * math.pi * 500, now=1000.0)

    assert first.id != second.id
    assert library.by_id(first.id) is first
    assert library.by_id(second.id) is second
    # And the wrong one must not be renamed or deleted by mistake.
    library.rename(second.id, "Second")
    assert first.name != "Second"


# ---- only circuits, and only the line actually driven ----------------------


def straight_line(length: float, n: int):
    return ([length * i / n for i in range(n)], [0.0] * n, [2] * n)


def out_and_back(length: float, n: int):
    half = n // 2
    xs = [length * i / half for i in range(half)]
    xs += [length * (1 - i / half) for i in range(half)]
    return (xs, [0.0] * len(xs), [2] * len(xs))


def test_a_straight_is_not_a_circuit(library):
    assert library.remember(*straight_line(3000.0, 300), 3000.0) is None
    assert library.tracks == []


def test_an_out_and_back_is_not_a_circuit(library):
    """It returns to its start but encloses nothing, so closure alone fails."""
    xs, zs, inputs = out_and_back(1500.0, 300)
    assert library.remember(xs, zs, inputs, 3000.0) is None
    assert library.tracks == []


def test_a_point_to_point_stage_is_not_a_circuit(library):
    xs = [3000.0 * i / 300 for i in range(300)]
    zs = [200.0 * math.sin(6 * math.pi * i / 300) for i in range(300)]
    assert library.remember(xs, zs, [2] * 300, 3946.0) is None


def test_a_very_thin_circuit_is_still_a_circuit(library):
    """The loop floor must not reject a real, straight-heavy road course."""
    xs = [2500.0 * math.cos(2 * math.pi * i / 400) for i in range(400)]
    zs = [165.0 * math.sin(2 * math.pi * i / 400) for i in range(400)]
    assert library.remember(xs, zs, [2] * 400, 10076.0) is not None


def test_non_circuits_are_forgotten_when_the_library_loads(tmp_path):
    """Maps saved before the loop test existed should not linger."""
    import json

    xs, zs, _ = circle(300.0, 200)
    good = {"id": "a", "name": "Circuit", "length": 1885.0,
            "points": [[round(x, 1), round(z, 1), 2] for x, z in zip(xs, zs)],
            "bbox": [-300, -300, 300, 300], "created": 1.0}
    line = {"id": "b", "name": "Straight", "length": 3000.0,
            "points": [[i * 10.0, 0.0, 2] for i in range(300)],
            "bbox": [0, 0, 3000, 0], "created": 2.0}
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps([good, line]))

    library = TrackLibrary(path)
    assert [t.name for t in library.tracks] == ["Circuit"]
    assert library.pruned_on_load == ["Straight"]
    # And the deletion is persisted, not just in memory.
    assert [t["name"] for t in json.loads(path.read_text())] == ["Circuit"]


def lap_of(radius: float, n: int, wide: tuple[int, int] | None = None):
    """A lap; `wide` runs off the usual line onto ground nobody else uses."""
    xs, zs, inputs = [], [], []
    for i in range(n):
        angle = 2 * math.pi * i / n
        r = radius + (120.0 if wide and wide[0] <= i < wide[1] else 0.0)
        xs.append(r * math.cos(angle))
        zs.append(r * math.sin(angle))
        inputs.append(2)
    return xs, zs, inputs


def deviation(track, radius: float = 400.0) -> float:
    return max(abs(math.hypot(p[0], p[1]) - radius) for p in track.points)


def test_an_excursion_does_not_overwrite_a_good_map(library):
    """The newest lap used to win outright, so one trip wide ruined the map."""
    for _ in range(3):
        clean = lap_of(400.0, 500)
        library.remember(*clean, path_length(clean[0], clean[1]))
    assert deviation(library.tracks[0]) < 5

    wide = lap_of(400.0, 500, wide=(150, 200))
    library.remember(*wide, path_length(wide[0], wide[1]))
    assert deviation(library.tracks[0]) < 5      # still the line actually used


def test_a_map_saved_from_a_scrappy_lap_recovers(library):
    wide = lap_of(400.0, 500, wide=(150, 200))
    library.remember(*wide, path_length(wide[0], wide[1]))
    assert deviation(library.tracks[0]) > 100    # the map starts out wrong

    clean = lap_of(400.0, 500)
    library.remember(*clean, path_length(clean[0], clean[1]))
    assert deviation(library.tracks[0]) < 5      # one clean lap is enough


def test_occupancy_records_where_the_car_actually_goes(library):
    for _ in range(3):
        clean = lap_of(400.0, 500)
        library.remember(*clean, path_length(clean[0], clean[1]))
    track = library.tracks[0]
    assert track.laps_seen == 3
    on_line = track.familiarity(*lap_of(400.0, 500)[:2])
    off_line = track.familiarity(*lap_of(400.0, 500, wide=(0, 500))[:2])
    assert on_line > 0.9
    assert off_line < 0.1


def test_one_off_ground_is_forgotten_once_there_is_a_consensus(library):
    wide = lap_of(400.0, 500, wide=(150, 200))
    library.remember(*wide, path_length(wide[0], wide[1]))
    for _ in range(3):
        clean = lap_of(400.0, 500)
        library.remember(*clean, path_length(clean[0], clean[1]))
    track = library.tracks[0]
    assert all(count > 1 for count in track.occupancy.values())
