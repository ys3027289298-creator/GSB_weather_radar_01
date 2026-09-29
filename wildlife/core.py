"""Wildlife patrol game core logic.

Stdlib only. Deterministic with a fixed seed. JSON save/load.
Run ``python -m wildlife.core`` for a fixed-seed CMD demo.
"""

import json
import random

DEMO_SEED = 84

FUEL_CAPACITY = 100
WATER_CAPACITY = 100
CAMERA_CAPACITY = 100
PHOTO_COST = 10
MEDKIT_CAPACITY = 10

DEFAULT_RESTRICTED = (3, 3, 6, 6)  # inclusive rectangle (x0, y0, x1, y1)


class GameError(Exception):
    """Raised for illegal commands or invalid state transitions."""


def _clamp(value, low, high):
    return max(low, min(high, value))


class Game:
    def __init__(self, seed=DEMO_SEED, width=10, height=10):
        self.seed = seed
        self.rng = random.Random(seed)
        self.width = width
        self.height = height
        self.restricted = DEFAULT_RESTRICTED
        self.fuel = FUEL_CAPACITY
        self.water = 0
        self.camera_battery = CAMERA_CAPACITY
        self.medkits = 3
        self.animals = {}       # id -> {"injured": bool}
        self.tracks = set()     # deduplicated footprint ids
        self.stations = {}      # water station id -> {"amount", "claimed"}
        self.storm_remaining = 0
        self.roads_blocked = False
        self.radio_working = True
        self.active_patrol = None  # {"fuel": reserved}
        self.teams_dispatched = 0
        self.turn = 0

    # --- map ---
    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def in_restricted(self, x, y):
        """Restricted zone check; boundary cells count as restricted."""
        if not self.in_bounds(x, y):
            raise GameError("position outside map")
        x0, y0, x1, y1 = self.restricted
        return x0 <= x <= x1 and y0 <= y <= y1

    # --- footprints ---
    def record_track(self, track_id):
        """Record a footprint. Duplicates are ignored, never double-counted."""
        if not track_id:
            raise GameError("empty track id")
        is_new = track_id not in self.tracks
        self.tracks.add(track_id)
        return is_new

    @property
    def track_count(self):
        return len(self.tracks)

    # --- animals ---
    def add_animal(self, animal_id, injured=False):
        if not animal_id:
            raise GameError("empty animal id")
        if animal_id in self.animals:
            raise GameError("duplicate animal id")
        self.animals[animal_id] = {"injured": bool(injured)}

    def treat_animal(self, animal_id):
        animal = self.animals.get(animal_id)
        if animal is None:
            raise GameError("unknown animal")
        if not animal["injured"]:
            return False  # already healthy; nothing to do
        if self.medkits <= 0:
            raise GameError("no medkits left")
        self.medkits -= 1
        animal["injured"] = False
        return True

    @property
    def injured_count(self):
        return sum(1 for a in self.animals.values() if a["injured"])

    # --- water ---
    def add_water_station(self, station_id, amount=20):
        if not station_id:
            raise GameError("empty station id")
        if station_id in self.stations:
            raise GameError("duplicate station id")
        self.stations[station_id] = {"amount": amount, "claimed": False}

    def claim_water(self, station_id):
        """Claim a water station once. Repeat claims are rejected."""
        station = self.stations.get(station_id)
        if station is None:
            raise GameError("unknown station")
        if station["claimed"]:
            raise GameError("station already claimed")
        station["claimed"] = True
        self.water = _clamp(self.water + station["amount"], 0, WATER_CAPACITY)
        return station["amount"]

    # --- storm / roads ---
    def start_storm(self, turns):
        if turns <= 0:
            raise GameError("storm duration must be positive")
        self.storm_remaining = turns
        self.roads_blocked = True

    def tick(self):
        """Advance one turn. Roads reopen only after the storm fully ends."""
        self.turn += 1
        if self.storm_remaining > 0:
            self.storm_remaining -= 1
        self.roads_blocked = self.storm_remaining > 0

    # --- radio / dispatch ---
    def set_radio(self, working):
        self.radio_working = bool(working)

    def dispatch_team(self):
        if not self.radio_working:
            raise GameError("radio failure: cannot dispatch")
        if self.roads_blocked:
            raise GameError("roads blocked by storm")
        self.teams_dispatched += 1
        return self.teams_dispatched

    # --- patrol / fuel ---
    def start_patrol(self, fuel_cost):
        if fuel_cost <= 0:
            raise GameError("fuel cost must be positive")
        if self.active_patrol is not None:
            raise GameError("patrol already active")
        if fuel_cost > self.fuel:
            raise GameError("not enough fuel")
        self.fuel -= fuel_cost
        self.active_patrol = {"fuel": fuel_cost}

    def cancel_patrol(self):
        """Cancel the active patrol and refund its reserved fuel."""
        if self.active_patrol is None:
            raise GameError("no active patrol")
        refund = self.active_patrol["fuel"]
        self.fuel = _clamp(self.fuel + refund, 0, FUEL_CAPACITY)
        self.active_patrol = None
        return refund

    # --- camera ---
    def take_photo(self):
        if self.camera_battery < PHOTO_COST:
            raise GameError("camera battery too low")
        self.camera_battery -= PHOTO_COST
        return self.camera_battery

    # --- save / load ---
    def to_dict(self):
        return {
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "restricted": list(self.restricted),
            "fuel": self.fuel,
            "water": self.water,
            "camera_battery": self.camera_battery,
            "medkits": self.medkits,
            "animals": self.animals,
            "tracks": sorted(self.tracks),
            "stations": self.stations,
            "storm_remaining": self.storm_remaining,
            "roads_blocked": self.roads_blocked,
            "radio_working": self.radio_working,
            "active_patrol": self.active_patrol,
            "teams_dispatched": self.teams_dispatched,
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            raise GameError("empty save data")
        game = cls(seed=data.get("seed", DEMO_SEED),
                   width=data.get("width", 10),
                   height=data.get("height", 10))
        game.restricted = tuple(data.get("restricted", DEFAULT_RESTRICTED))
        game.fuel = _clamp(int(data.get("fuel", FUEL_CAPACITY)), 0, FUEL_CAPACITY)
        game.water = _clamp(int(data.get("water", 0)), 0, WATER_CAPACITY)
        # Battery is stored as an exact integer so save/load never drifts.
        game.camera_battery = _clamp(int(data.get("camera_battery", CAMERA_CAPACITY)),
                                     0, CAMERA_CAPACITY)
        game.medkits = _clamp(int(data.get("medkits", 3)), 0, MEDKIT_CAPACITY)
        game.animals = {k: {"injured": bool(v["injured"])}
                        for k, v in data.get("animals", {}).items()}
        game.tracks = set(data.get("tracks", []))
        game.stations = {k: {"amount": int(v["amount"]),
                             "claimed": bool(v["claimed"])}
                         for k, v in data.get("stations", {}).items()}
        game.storm_remaining = max(0, int(data.get("storm_remaining", 0)))
        game.roads_blocked = game.storm_remaining > 0
        game.radio_working = bool(data.get("radio_working", True))
        game.active_patrol = data.get("active_patrol")
        game.teams_dispatched = max(0, int(data.get("teams_dispatched", 0)))
        game.turn = max(0, int(data.get("turn", 0)))
        return game

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    # --- command interface ---
    def execute(self, command_line):
        """Execute a text command. Illegal commands raise GameError."""
        if not command_line or not command_line.strip():
            raise GameError("empty command")
        parts = command_line.split()
        cmd, args = parts[0], parts[1:]
        if cmd == "track" and len(args) == 1:
            return self.record_track(args[0])
        if cmd == "treat" and len(args) == 1:
            return self.treat_animal(args[0])
        if cmd == "claim" and len(args) == 1:
            return self.claim_water(args[0])
        if cmd == "storm" and len(args) == 1:
            return self.start_storm(int(args[0]))
        if cmd == "tick" and not args:
            return self.tick()
        if cmd == "radio" and len(args) == 1 and args[0] in ("on", "off"):
            return self.set_radio(args[0] == "on")
        if cmd == "dispatch" and not args:
            return self.dispatch_team()
        if cmd == "photo" and not args:
            return self.take_photo()
        if cmd == "patrol" and len(args) == 2 and args[0] == "start":
            return self.start_patrol(int(args[1]))
        if cmd == "patrol" and len(args) == 1 and args[0] == "cancel":
            return self.cancel_patrol()
        if cmd == "status" and not args:
            return self.status()
        raise GameError("illegal command: %s" % command_line)

    def status(self):
        return {
            "turn": self.turn,
            "fuel": self.fuel,
            "water": self.water,
            "camera_battery": self.camera_battery,
            "medkits": self.medkits,
            "injured": self.injured_count,
            "tracks": self.track_count,
            "storm_remaining": self.storm_remaining,
            "roads_blocked": self.roads_blocked,
            "radio_working": self.radio_working,
            "patrol_active": self.active_patrol is not None,
            "teams_dispatched": self.teams_dispatched,
        }


def run_demo(seed=DEMO_SEED):
    """Fixed-seed CMD demo; deterministic transcript."""
    game = Game(seed=seed)
    lines = ["wildlife patrol demo (seed=%d)" % seed]
    game.add_animal("A1", injured=True)
    game.add_animal("A2", injured=True)
    game.add_water_station("S1", amount=30)
    script = [
        "track T1", "track T1", "track T2",      # duplicate ignored
        "treat A1",                               # A1 no longer injured
        "claim S1",                               # +30 water
        "storm 2", "tick",                        # still blocked
        "patrol start 40", "patrol cancel",       # fuel refunded
        "photo", "photo",
        "tick",                                   # storm ends, roads open
        "dispatch",
        "status",
    ]
    for command in script:
        result = game.execute(command)
        lines.append("> %s" % command)
        if command == "status":
            for key, value in sorted(result.items()):
                lines.append("  %s: %s" % (key, value))
        elif result is not None:
            lines.append("  -> %s" % (result,))
    lines.append("demo complete")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run_demo())
