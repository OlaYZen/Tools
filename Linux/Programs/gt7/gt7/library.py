"""Saved track outlines, and recognising which one you are driving.

GT7 gives every circuit its own coordinate space, and a car at a given point on
a given track reports the same world position every session. That makes
recognition a spatial question rather than a shape-matching one: take where the
car has been over the last few hundred metres and ask which saved outline those
points land on.

The index is a grid hash whose cell size *is* the match tolerance, so a lookup
is a handful of dictionary hits rather than a scan over every stored point.

Matching is deliberately sticky. A circuit that flickered in and out as the car
crossed a pit lane or a shared section would be worse than no recognition at
all, so a candidate must win several consecutive checks before it is adopted,
and must fall well below the adoption threshold before it is dropped.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Grid cell size and match tolerance in metres. A point counts as "on" a
#: saved track if a stored point lies within this distance.
MATCH_CELL = 25.0

#: Fraction of recent points that must land on a track to adopt it, and the
#: fraction it must fall below before it is dropped. The gap between the two
#: is what stops a borderline match oscillating.
MATCH_MIN = 0.6
MATCH_DROP = 0.3

#: How many recent points to test, and how many consecutive checks a candidate
#: must win before it is adopted or abandoned.
MATCH_WINDOW = 140
MATCH_HOLD = 3

#: Spacing for stored points. Coarser than the live trace: a saved outline is
#: drawn small, and every stored point costs file size forever.
SAVE_SPACING = 6.0

#: Two outlines whose lengths differ by more than this are not the same
#: circuit, whatever the spatial overlap says. Guards against a short layout
#: that shares most of its route with a longer one.
LENGTH_TOLERANCE = 0.25

MAX_TRACKS = 100

#: A pit lane never approaches the length of the lap it serves.
MAX_LANE_FRACTION = 0.6

#: Grid for counting how often each patch of ground has been driven. Coarser
#: than the match tolerance, because this is about "have we been here before"
#: rather than "is this the same circuit".
OCCUPANCY_CELL = 8.0

#: A saved outline is only replaced by a lap that runs over better-trodden
#: ground than the one already stored. Without this the newest lap always won,
#: so a single excursion overwrote a good map with a bad one.
#: Scores are mean visits per point, normalised by laps seen.

#: How close a lap must come back to its start to count as a loop.
LOOP_GAP_METRES = 60.0
LOOP_GAP_FRACTION = 0.03

#: Enclosed area over length squared. A circuit encloses ground; a straight,
#: an out-and-back or a rally stage does not. Measured shapes: a circle scores
#: 0.080, a 3:1 road course 0.053, a very thin 15:1 circuit 0.013, a wiggly
#: point-to-point stage 0.0012, and a straight or out-and-back exactly 0.
#: The floor sits well under the thinnest plausible circuit.
MIN_LOOP_AREA_RATIO = 0.003


def loop_metrics(points: list[list[float]]) -> tuple[float, float, float]:
    """(path length, start-to-end gap, enclosed area / length squared)."""
    if len(points) < 4:
        return 0.0, 0.0, 0.0
    length = 0.0
    for i in range(1, len(points)):
        length += ((points[i][0] - points[i - 1][0]) ** 2
                   + (points[i][1] - points[i - 1][1]) ** 2) ** 0.5
    gap = ((points[0][0] - points[-1][0]) ** 2
           + (points[0][1] - points[-1][1]) ** 2) ** 0.5
    twice_area = 0.0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        twice_area += points[i][0] * points[j][1] - points[j][0] * points[i][1]
    ratio = abs(twice_area) / 2 / (length ** 2) if length else 0.0
    return length, gap, ratio


def is_loop(points: list[list[float]]) -> bool:
    """True if this really is a circuit, rather than a line the car drove down.

    Both tests are needed. Closure alone accepts an out-and-back, which returns
    to its start while enclosing nothing; enclosed area alone accepts a lap
    that never came back.
    """
    length, gap, ratio = loop_metrics(points)
    if length <= 0:
        return False
    if gap > max(LOOP_GAP_METRES, length * LOOP_GAP_FRACTION):
        return False
    return ratio >= MIN_LOOP_AREA_RATIO


def _cell_key(x: float, z: float) -> str:
    return f"{int(x // OCCUPANCY_CELL)},{int(z // OCCUPANCY_CELL)}"


def default_path() -> Path:
    """Where the library lives when the caller does not say."""
    root = os.environ.get("XDG_DATA_HOME")
    base = Path(root) if root else Path.home() / ".local" / "share"
    return base / "gt7" / "tracks.json"


@dataclass
class SavedTrack:
    id: str
    name: str
    length: float
    #: (x, z, input) triples, rounded to the metre.
    points: list[list[float]]
    bbox: list[float]
    created: float
    laps_seen: int = 1
    #: How many laps have run through each patch of ground. This is the record
    #: of where the driver actually goes, as opposed to where they went once.
    occupancy: dict[str, int] = field(default_factory=dict)
    #: The pit road, drawn as a thin branch off the circuit. Kept separate from
    #: `points` because it is not part of a lap.
    pit_lane: list[list[float]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": self.id, "name": self.name, "length": self.length,
            "points": self.points, "bbox": self.bbox,
            "created": self.created, "laps_seen": self.laps_seen,
            "occupancy": self.occupancy, "pit_lane": self.pit_lane,
        }

    @classmethod
    def from_json(cls, raw: dict) -> SavedTrack:
        return cls(
            id=str(raw["id"]), name=str(raw["name"]),
            length=float(raw["length"]), points=list(raw["points"]),
            bbox=list(raw["bbox"]), created=float(raw.get("created", 0.0)),
            laps_seen=int(raw.get("laps_seen", 1)),
            occupancy={str(k): int(v) for k, v in (raw.get("occupancy") or {}).items()},
            pit_lane=list(raw.get("pit_lane") or []),
        )

    def visit(self, xs: list[float], zs: list[float]) -> None:
        """Record that a lap ran over this ground."""
        for cell in {_cell_key(x, z) for x, z in zip(xs, zs)}:
            self.occupancy[cell] = self.occupancy.get(cell, 0) + 1

    def familiarity(self, xs: list[float], zs: list[float]) -> float:
        """How well-trodden the ground under these points is, 0..1.

        A lap that follows the usual line scores near 1; one that ran wide
        onto ground nobody visits scores lower in proportion to how far it
        strayed.
        """
        if not xs or not self.laps_seen:
            return 0.0
        total = sum(min(self.occupancy.get(_cell_key(x, z), 0), self.laps_seen)
                    for x, z in zip(xs, zs))
        return total / (len(xs) * self.laps_seen)

    def forget_one_offs(self) -> None:
        """Drop ground visited on a single lap once there is a consensus.

        Keeps the file small and, more to the point, stops one excursion
        counting as evidence for ever.
        """
        if self.laps_seen < 3:
            return
        self.occupancy = {k: v for k, v in self.occupancy.items() if v > 1}


def downsample(xs: list[float], zs: list[float], inputs: list[int],
               spacing: float = SAVE_SPACING) -> list[list[float]]:
    out: list[list[float]] = []
    last: tuple[float, float] | None = None
    for x, z, state in zip(xs, zs, inputs):
        if last is None or ((x - last[0]) ** 2 + (z - last[1]) ** 2) ** 0.5 >= spacing:
            out.append([round(x, 1), round(z, 1), int(state)])
            last = (x, z)
    return out


class TrackLibrary:
    """Stores outlines and works out which one the car is on."""

    def __init__(self, path: Path | None = None, autoload: bool = True) -> None:
        self.path = path or default_path()
        self.tracks: list[SavedTrack] = []
        self._index: dict[tuple[int, int], list[tuple[str, float, float]]] = {}

        # Sticky-match state.
        self.active_id: str | None = None
        #: Names dropped by the loop test when the library was loaded, so the
        #: server can say what it threw away rather than doing it silently.
        self.pruned_on_load: list[str] = []
        self._candidate: str | None = None
        self._candidate_runs = 0
        self._lost_runs = 0

        if autoload:
            self.load()

    # ---- persistence ----------------------------------------------------

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.tracks = []          # missing or corrupt: start empty, do not crash
            self._reindex()
            return
        tracks = []
        for entry in raw if isinstance(raw, list) else []:
            try:
                tracks.append(SavedTrack.from_json(entry))
            except (KeyError, TypeError, ValueError):
                continue              # skip a bad row rather than lose the file
        self.tracks = tracks
        self._reindex()
        # Older libraries may hold straights saved before the loop test
        # existed. Clear them out rather than leaving them to be matched.
        self.pruned_on_load = self.prune()

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file so an interrupted save cannot truncate the
        # library to nothing.
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps([t.to_json() for t in self.tracks]))
        temp.replace(self.path)

    # ---- index ----------------------------------------------------------

    def _reindex(self) -> None:
        self._index = {}
        for track in self.tracks:
            for x, z, _ in track.points:
                key = (int(x // MATCH_CELL), int(z // MATCH_CELL))
                self._index.setdefault(key, []).append((track.id, x, z))

    def _new_id(self, stamp: float) -> str:
        """A millisecond stamp, disambiguated if one is already taken.

        Two laps saved inside the same millisecond used to collide, and a
        colliding id makes `by_id` return the wrong circuit - so rename and
        forget would act on someone else's track.
        """
        base = f"t{int(stamp * 1000):x}"
        taken = {t.id for t in self.tracks}
        if base not in taken:
            return base
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"

    def near_active(self, x: float, z: float,
                    tolerance: float | None = None) -> bool | None:
        """Is this point on the active circuit's racing line?

        None when no circuit is recognised, so callers can tell "off the line"
        from "we have no idea where the line is".

        Tested against the stored *outline*, never the occupancy record: the
        pit lane gets driven repeatedly too, so occupancy learns it, while the
        outline only ever comes from a clean racing lap.
        """
        track = self.by_id(self.active_id)
        if track is None:
            return None
        # Callers asking "on the track or beside it?" need a far tighter
        # figure than circuit matching uses; MATCH_CELL is only the default.
        limit = (tolerance if tolerance is not None else MATCH_CELL) ** 2
        cx, cz = int(x // MATCH_CELL), int(z // MATCH_CELL)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for tid, qx, qz in self._index.get((cx + dx, cz + dz), ()):
                    if tid != track.id:
                        continue
                    if (x - qx) ** 2 + (z - qz) ** 2 <= limit:
                        return True
        return False

    def by_id(self, track_id: str | None) -> SavedTrack | None:
        if track_id is None:
            return None
        return next((t for t in self.tracks if t.id == track_id), None)

    # ---- matching -------------------------------------------------------

    def score(self, xs: list[float], zs: list[float]) -> tuple[str | None, float]:
        """Best-matching saved track for these points, and how well it fits."""
        if not self.tracks or len(xs) < 8:
            return None, 0.0
        window = min(len(xs), MATCH_WINDOW)
        tol_sq = MATCH_CELL * MATCH_CELL
        hits: dict[str, int] = {}

        for i in range(len(xs) - window, len(xs)):
            px, pz = xs[i], zs[i]
            cx, cz = int(px // MATCH_CELL), int(pz // MATCH_CELL)
            near: set[str] = set()
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for tid, qx, qz in self._index.get((cx + dx, cz + dz), ()):
                        if tid in near:
                            continue
                        if (px - qx) ** 2 + (pz - qz) ** 2 <= tol_sq:
                            near.add(tid)
            for tid in near:
                hits[tid] = hits.get(tid, 0) + 1

        if not hits:
            return None, 0.0
        best = max(hits.items(), key=lambda kv: kv[1])
        return best[0], best[1] / window

    def update_match(self, xs: list[float], zs: list[float]) -> SavedTrack | None:
        """Follow the car, adopting or dropping a track with hysteresis."""
        track_id, fraction = self.score(xs, zs)

        if track_id and fraction >= MATCH_MIN:
            self._lost_runs = 0
            if track_id != self.active_id:
                if track_id == self._candidate:
                    self._candidate_runs += 1
                else:
                    self._candidate = track_id
                    self._candidate_runs = 1
                if self._candidate_runs >= MATCH_HOLD:
                    self.active_id = track_id
                    self._candidate = None
                    self._candidate_runs = 0
        else:
            self._candidate = None
            self._candidate_runs = 0
            if self.active_id and fraction < MATCH_DROP:
                self._lost_runs += 1
                if self._lost_runs >= MATCH_HOLD * 2:
                    self.active_id = None
                    self._lost_runs = 0
        return self.by_id(self.active_id)

    # ---- saving a completed lap -----------------------------------------

    def remember(self, xs: list[float], zs: list[float], inputs: list[int],
                 length: float, now: float | None = None) -> SavedTrack | None:
        """Store a completed lap, or refresh the saved track it matches.

        Returns the track it became, or None if the lap was not a circuit.
        """
        points = downsample(xs, zs, inputs)
        if len(points) < 12:
            return None
        if not is_loop(points):
            # A straight, an out-and-back or a point-to-point stage. Saving it
            # would fill the library with roads that are not circuits.
            return None

        track_id, fraction = self.score(xs, zs)
        existing = self.by_id(track_id) if fraction >= MATCH_MIN else None
        if existing is not None and _length_agrees(existing.length, length):
            return self._refresh(existing, xs, zs, points, length)

        stamp = now if now is not None else time.time()
        track = SavedTrack(
            id=self._new_id(stamp),
            name=f"Track {len(self.tracks) + 1}",
            length=round(length, 1),
            points=points,
            bbox=_bbox(points),
            created=stamp,
        )
        track.visit(xs, zs)
        self.tracks.append(track)
        while len(self.tracks) > MAX_TRACKS:
            self.tracks.pop(0)
        self._reindex()
        self.persist()
        self.active_id = track.id
        return track

    def _refresh(self, track: SavedTrack, xs: list[float], zs: list[float],
                 points: list[list[float]], length: float) -> SavedTrack:
        """Fold another lap of this circuit into what we know about it.

        The stored outline is only replaced by a lap that runs over
        better-trodden ground than the one already held. Previously the newest
        lap always won, so one trip through the gravel overwrote a good map and
        it stayed wrong.

        Both laps are scored *after* this one is counted, so neither is judged
        against a record that includes only itself. On a tie the newer lap
        wins, which is what lets a map saved from a scrappy first lap recover
        as soon as a clean one is driven.
        """
        track.visit(xs, zs)
        track.laps_seen += 1

        incumbent = track.familiarity([p[0] for p in track.points],
                                      [p[1] for p in track.points])
        challenger = track.familiarity(xs, zs)
        if challenger >= incumbent:
            track.points = points
            track.length = round(length, 1)
            track.bbox = _bbox(points)

        track.forget_one_offs()
        self._reindex()
        self.persist()
        self.active_id = track.id
        return track

    # ---- housekeeping ---------------------------------------------------

    def remember_pit_lane(self, track_id: str | None,
                          path: list[tuple[float, float]]) -> bool:
        """Attach the pit road to a circuit, keeping the fullest run of it.

        A stop entered late or left early traces only part of the lane, so the
        longest traversal seen wins rather than the most recent.
        """
        track = self.by_id(track_id)
        if track is None or len(path) < 4:
            return False
        thinned = [[round(x, 1), round(z, 1)] for x, z in path]
        length = _path_length(thinned)
        # A pit lane is a fraction of a lap. Anything longer is a stop that
        # failed to close, recording racing line as if it were pit road - and
        # "longest wins" would then enshrine the corrupt one permanently.
        if length > track.length * MAX_LANE_FRACTION:
            return False
        if length <= _path_length(track.pit_lane):
            return False
        track.pit_lane = thinned
        self.persist()
        return True

    def prune(self) -> list[str]:
        """Forget saved outlines that are not circuits. Returns their names."""
        doomed = [t for t in self.tracks if not is_loop(t.points)]
        for track in doomed:
            self.tracks.remove(track)
            if self.active_id == track.id:
                self.active_id = None
        if doomed:
            self._reindex()
            self.persist()
        return [t.name for t in doomed]

    def rename(self, track_id: str, name: str) -> SavedTrack | None:
        track = self.by_id(track_id)
        if track is None:
            return None
        track.name = name.strip()[:60] or track.name
        self.persist()
        return track

    def forget(self, track_id: str) -> bool:
        track = self.by_id(track_id)
        if track is None:
            return False
        self.tracks.remove(track)
        if self.active_id == track_id:
            self.active_id = None
        self._reindex()
        self.persist()
        return True


def _path_length(points: list[list[float]]) -> float:
    return sum(((points[i][0] - points[i - 1][0]) ** 2
                + (points[i][1] - points[i - 1][1]) ** 2) ** 0.5
               for i in range(1, len(points)))


def _bbox(points: list[list[float]]) -> list[float]:
    xs = [p[0] for p in points]
    zs = [p[1] for p in points]
    return [min(xs), min(zs), max(xs), max(zs)]


def _length_agrees(a: float, b: float) -> bool:
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= LENGTH_TOLERANCE
