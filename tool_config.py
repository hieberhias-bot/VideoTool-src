import json
import os
import logging

_logger = logging.getLogger("ToolConfig")
DEFAULT_CONFIG_PATH = "tool_config.json"

_DEFAULTS = {
    "template_scale_min": 1.0,
    "template_scale_max": 1.7,
    "template_scale_steps": 8,
    "grab_hue_target": 148,
    "grab_hue_tolerance": 20,
    "grab_sat_min": 70,
    "grab_val_min": 100,
    "grab_min_area_ratio": 0.005,
    "fish_value_max": 140,
    "fish_min_area_ratio": 0.001,
    "fish_band_top": 0.06,
    "fish_band_bottom": 0.84,
    "fish_use_motion": False,
    "fish_motion_warmup": 30,
    "fish_track_hold_frames": 30,
    "fish_track_gate_ratio": 0.5,
    "circle_radius_min_frac": 0.28,
    "circle_radius_max_frac": 0.55,
    "circle_sensitivity": 35,
    "circle_hitbox_frac": 0.12,
    "trigger_fire_prob": 0.2,
}

class ToolConfig:
    def __init__(self, path=DEFAULT_CONFIG_PATH, auto_load=True):
        self.__path = path
        self.__values = dict(_DEFAULTS)
        if auto_load:
            self.load()
    def get(self, key):
        return self.__values[key]
    def set(self, key, value):
        if key not in _DEFAULTS:
            raise KeyError(key)
        self.__values[key] = value
    def as_dict(self):
        return dict(self.__values)
    def load(self):
        if not os.path.exists(self.__path):
            return
        try:
            with open(self.__path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k in _DEFAULTS:
                if k in raw:
                    self.__values[k] = raw[k]
        except (json.JSONDecodeError, OSError):
            pass
    def save(self):
        with open(self.__path, "w", encoding="utf-8") as f:
            json.dump(self.__values, f, indent=4, ensure_ascii=False)
