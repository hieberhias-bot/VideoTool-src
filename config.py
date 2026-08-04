import json
import os
import logging
from typing import Any, Dict

_logger = logging.getLogger("ToolConfig")

# Default name of the config file, stored next to the source files.
DEFAULT_CONFIG_PATH = "tool_config.json"


class ToolConfig:
    """
    Manages the general settings of the video tool.

    The settings are grouped into three sections (GENERAL, DETECTION, OUTPUT).
    Every setting is described by a schema entry holding its default value,
    the allowed range (min/max), a human readable description and the value
    type. The schema is the single source of truth: it is used to build the
    default configuration, to validate values on load/set and to drive the
    CLI menu in config_ui.py.

    The values are persisted as JSON in tool_config.json and reloaded on start.
    Values that are out of range or of the wrong type are reset to their
    default while loading, so a corrupted or hand-edited file can never crash
    the tool.
    """

    # Schema for every setting.
    #   type:    "choice" | "bool" | "int" | "float" | "str"
    #   default: the value used when nothing is stored / a value is invalid
    #   min/max: numeric bounds (None if not applicable)
    #   choices: allowed values for "choice" type (None otherwise)
    #   desc:    human readable description shown in the UI
    SCHEMA: Dict[str, Dict[str, Dict[str, Any]]] = {
        "GENERAL": {
            "log_level": {
                "type": "choice",
                "default": "INFO",
                "min": None,
                "max": None,
                "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
                "desc": "Logging-Level",
            },
            "save_screenshots": {
                "type": "bool",
                "default": False,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Screenshots speichern",
            },
            "screenshot_interval": {
                "type": "int",
                "default": 5,
                "min": 1,
                "max": 3600,
                "choices": None,
                "desc": "Sekunden zwischen Screenshots",
            },
        },
        "DETECTION": {
            "template_match_threshold": {
                "type": "float",
                "default": 0.7,
                "min": 0.5,
                "max": 1.0,
                "choices": None,
                "desc": "Schwellwert für Template-Matching",
            },
            "color_match_tolerance": {
                "type": "int",
                "default": 20,
                "min": 0,
                "max": 255,
                "choices": None,
                "desc": "Toleranz für Farb-Matching",
            },
            "scan_interval_ms": {
                "type": "int",
                "default": 100,
                "min": 1,
                "max": 60000,
                "choices": None,
                "desc": "Intervall für Bildschirm-Scans (ms)",
            },
            "template_scale_min": {
                "type": "float",
                "default": 1.0,
                "min": 0.5,
                "max": 3.0,
                "choices": None,
                "desc": "Kleinste Template-Skala (Multi-Scale-Suche)",
            },
            "template_scale_max": {
                "type": "float",
                "default": 1.7,
                "min": 0.5,
                "max": 3.0,
                "choices": None,
                "desc": "Größte Template-Skala (Multi-Scale-Suche)",
            },
            "template_scale_steps": {
                "type": "int",
                "default": 8,
                "min": 1,
                "max": 40,
                "choices": None,
                "desc": "Anzahl Skalen-Stufen (mehr = robuster, langsamer)",
            },
        },
        # Biss-Indikator (grab): HSV-Farb-Segmentierung (H-Kanal 0-179).
        # Fisch (fish): Helligkeits-Segmentierung - die Fisch-Silhouette ist ein
        # dunkler Umriss auf hellem Wasser, daher ueber V (dunkel) statt Farbton.
        "COLOR_DETECTION": {
            "grab_hue_target": {
                "type": "int",
                "default": 148,
                "min": 0,
                "max": 179,
                "choices": None,
                "desc": "Ziel-Farbton Biss-Marker (H, 0-179; ~148 = Magenta)",
            },
            "grab_hue_tolerance": {
                "type": "int",
                "default": 20,
                "min": 0,
                "max": 30,
                "choices": None,
                "desc": "Farbton-Toleranz Biss-Marker",
            },
            "grab_sat_min": {
                "type": "int",
                "default": 70,
                "min": 0,
                "max": 255,
                "choices": None,
                "desc": "Minimale Sättigung Biss-Marker",
            },
            "grab_val_min": {
                "type": "int",
                "default": 100,
                "min": 0,
                "max": 255,
                "choices": None,
                "desc": "Minimale Helligkeit Biss-Marker",
            },
            "grab_min_area_ratio": {
                "type": "float",
                "default": 0.005,
                "min": 0.0,
                "max": 0.5,
                "choices": None,
                "desc": "Mindest-Flächenanteil Magenta für 'fischbar' (Pixel/ROI)",
            },
            "fish_value_max": {
                "type": "int",
                "default": 140,
                "min": 0,
                "max": 255,
                "choices": None,
                "desc": "Max. Helligkeit für Fisch (dunkler = Fisch)",
            },
            "fish_min_area_ratio": {
                "type": "float",
                "default": 0.001,
                "min": 0.0,
                "max": 0.2,
                "choices": None,
                "desc": "Mindest-Fläche der Fisch-Silhouette (Anteil der ROI)",
            },
            "fish_band_top": {
                "type": "float",
                "default": 0.06,
                "min": 0.0,
                "max": 0.5,
                "choices": None,
                "desc": "Oberer Rand-Ausschluss der Wasserfläche (Anteil)",
            },
            "fish_band_bottom": {
                "type": "float",
                "default": 0.84,
                "min": 0.5,
                "max": 1.0,
                "choices": None,
                "desc": "Unteres Ende der Wasserfläche (Anteil, blendet Balken aus)",
            },
            "fish_track_hold_frames": {
                "type": "int",
                "default": 30,
                "min": 0,
                "max": 300,
                "choices": None,
                "desc": "Frames, die die Fisch-Spur ohne Treffer gehalten wird",
            },
            "fish_track_gate_ratio": {
                "type": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 2.0,
                "choices": None,
                "desc": "Max. Sprung eines Treffers zur Spur (Anteil ROI-Diagonale)",
            },
            "fish_use_motion": {
                "type": "bool",
                "default": False,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Bewegungserkennung (MOG2) dazu (braucht stabiles Fenster)",
            },
            "fish_motion_warmup": {
                "type": "int",
                "default": 30,
                "min": 0,
                "max": 300,
                "choices": None,
                "desc": "Frames Aufwärmzeit des Bewegungsmodells je Episode",
            },
            "circle_radius_min_frac": {
                "type": "float",
                "default": 0.28,
                "min": 0.1,
                "max": 0.6,
                "choices": None,
                "desc": "Min. Zielkreis-Radius (Anteil ROI-Höhe)",
            },
            "circle_radius_max_frac": {
                "type": "float",
                "default": 0.55,
                "min": 0.3,
                "max": 0.9,
                "choices": None,
                "desc": "Max. Zielkreis-Radius (Anteil ROI-Höhe)",
            },
            "circle_sensitivity": {
                "type": "int",
                "default": 35,
                "min": 10,
                "max": 100,
                "choices": None,
                "desc": "Hough-Empfindlichkeit Zielkreis (kleiner = mehr Treffer)",
            },
        },
        "OUTPUT": {
            "output_format": {
                "type": "choice",
                "default": "json",
                "min": None,
                "max": None,
                "choices": ["json", "csv", "both"],
                "desc": "Ausgabe-Format",
            },
            "output_dir": {
                "type": "str",
                "default": "output",
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Ausgabe-Verzeichnis",
            },
            "save_results": {
                "type": "bool",
                "default": True,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Ergebnisse speichern",
            },
        },
        # Entzerrt Bildschirm-Scans und Verarbeitungsaktionen, um CPU-Last zu
        # reduzieren und eine natuerliche Verarbeitungsgeschwindigkeit zu
        # simulieren.
        "TIMING": {
            "scan_delay_min_ms": {
                "type": "int",
                "default": 100,
                "min": 50,
                "max": 2000,
                "choices": None,
                "desc": "Minimale Verzögerung zwischen Scans (ms)",
            },
            "scan_delay_max_ms": {
                "type": "int",
                "default": 300,
                "min": 50,
                "max": 2000,
                "choices": None,
                "desc": "Maximale Verzögerung zwischen Scans (ms)",
            },
            "action_delay_min_ms": {
                "type": "int",
                "default": 150,
                "min": 50,
                "max": 2000,
                "choices": None,
                "desc": "Minimale Verzögerung zwischen Aktionen (ms)",
            },
            "action_delay_max_ms": {
                "type": "int",
                "default": 500,
                "min": 50,
                "max": 2000,
                "choices": None,
                "desc": "Maximale Verzögerung zwischen Aktionen (ms)",
            },
            "randomize_delays": {
                "type": "bool",
                "default": True,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Zufällige Verzögerungen verwenden",
            },
        },
        # Steuert, wie der Cursor/Zeiger zu erkannten Zielen bewegt wird:
        # geglättete Pfade, Bézier-Kurven und zufällige Abweichung (Jitter),
        # damit die ausgeloesten Bewegungen natuerlich wirken.
        "MOVEMENT": {
            "smooth_movement": {
                "type": "bool",
                "default": True,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Glatte Bewegungsübergänge verwenden",
            },
            "bezier_curve": {
                "type": "bool",
                "default": True,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Bézier-Kurven für Bewegungen verwenden",
            },
            "movement_speed_min": {
                "type": "float",
                "default": 1.0,
                "min": 0.1,
                "max": 10.0,
                "choices": None,
                "desc": "Minimale Bewegungsgeschwindigkeit",
            },
            "movement_speed_max": {
                "type": "float",
                "default": 3.0,
                "min": 0.1,
                "max": 10.0,
                "choices": None,
                "desc": "Maximale Bewegungsgeschwindigkeit",
            },
            "jitter_amount": {
                "type": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 5.0,
                "choices": None,
                "desc": "Zufällige Abweichung für natürliche Bewegungen",
            },
            "jitter_frequency": {
                "type": "float",
                "default": 2.0,
                "min": 0.0,
                "max": 10.0,
                "choices": None,
                "desc": "Häufigkeit der Abweichungen",
            },
        },
        # Fügt den ausgeloesten Klicks/Aktionen absichtlich Unregelmaessigkeiten
        # hinzu (gelegentliche Doppelklicks, langsame Klicks, Fehlklicks), damit
        # die erzeugten Eingaben weniger mechanisch wirken.
        "ERROR_SIMULATION": {
            "simulate_errors": {
                "type": "bool",
                "default": False,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Fehler simulieren",
            },
            "error_rate_percent": {
                "type": "float",
                "default": 2.0,
                "min": 0.0,
                "max": 20.0,
                "choices": None,
                "desc": "Fehlerrate in Prozent",
            },
            "double_click_rate": {
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 10.0,
                "choices": None,
                "desc": "Doppelklick-Rate in Prozent",
            },
            "slow_click_rate": {
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 10.0,
                "choices": None,
                "desc": "Langsame Klick-Rate in Prozent",
            },
            "miss_rate_percent": {
                "type": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 10.0,
                "choices": None,
                "desc": "Verfehlungsrate in Prozent",
            },
        },
        # Formt die erzeugten Eingaben so, dass sie menschlichem Verhalten
        # aehneln: simulierte Reaktionszeit, variable Klickdauer und ein
        # zufaelliges Bewegungs-Rauschen.
        "HUMANIZATION": {
            "humanize_input": {
                "type": "bool",
                "default": True,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Menschliche Eingaben simulieren",
            },
            "reaction_time_min_ms": {
                "type": "int",
                "default": 300,
                "min": 100,
                "max": 3000,
                "choices": None,
                "desc": "Minimale Reaktionszeit (ms)",
            },
            "reaction_time_max_ms": {
                "type": "int",
                "default": 800,
                "min": 100,
                "max": 3000,
                "choices": None,
                "desc": "Maximale Reaktionszeit (ms)",
            },
            "click_duration_min_ms": {
                "type": "int",
                "default": 80,
                "min": 50,
                "max": 500,
                "choices": None,
                "desc": "Minimale Klickdauer (ms)",
            },
            "click_duration_max_ms": {
                "type": "int",
                "default": 150,
                "min": 50,
                "max": 500,
                "choices": None,
                "desc": "Maximale Klickdauer (ms)",
            },
            "movement_noise": {
                "type": "float",
                "default": 0.3,
                "min": 0.0,
                "max": 2.0,
                "choices": None,
                "desc": "Zufälliges Rauschen in Bewegungen",
            },
        },
        # Automatische Arbeits-/Pausen-Zyklen: nach einer zufaelligen Arbeitszeit
        # pausiert das Tool fuer eine zufaellige Dauer und laeuft dann weiter.
        "PAUSES": {
            "pause_enabled": {
                "type": "bool",
                "default": False,
                "min": None,
                "max": None,
                "choices": None,
                "desc": "Pausen an/aus",
            },
            "work_minutes_min": {
                "type": "int",
                "default": 20,
                "min": 1,
                "max": 120,
                "choices": None,
                "desc": "Minimale Arbeitszeit (Minuten)",
            },
            "work_minutes_max": {
                "type": "int",
                "default": 40,
                "min": 1,
                "max": 120,
                "choices": None,
                "desc": "Maximale Arbeitszeit (Minuten)",
            },
            "pause_seconds_min": {
                "type": "int",
                "default": 30,
                "min": 5,
                "max": 600,
                "choices": None,
                "desc": "Minimale Pausendauer (Sekunden)",
            },
            "pause_seconds_max": {
                "type": "int",
                "default": 120,
                "min": 5,
                "max": 600,
                "choices": None,
                "desc": "Maximale Pausendauer (Sekunden)",
            },
        },
        # Fang-Trigger (nur Erkennung, klickt nichts): der Fisch gilt als
        # fangbar, sobald er im Zielkreis / auf dem Ring (Hitbox) erreichbar ist
        # - ob still oder im Durchflitzen. Es wird hoechstens EINMAL pro Eintritt
        # ausgeloest, an einem zufaelligen Zeitpunkt (nicht immer sofort).
        "CATCH": {
            "circle_hitbox_frac": {
                "type": "float",
                "default": 0.12,
                "min": 0.0,
                "max": 0.5,
                "choices": None,
                "desc": "Ring-Hitbox über den Kreisradius hinaus (Anteil r)",
            },
            "trigger_fire_prob": {
                "type": "float",
                "default": 0.2,
                "min": 0.0,
                "max": 1.0,
                "choices": None,
                "desc": "Auslöse-Chance je Frame im Kreis (zufäll. Timing, max 1x/Eintritt)",
            },
        },
    }

    # Pairs of settings where the "min" value must not exceed the "max" value.
    # Format: (min_key, max_key, human readable label).
    PAIRS = [
        ("scan_delay_min_ms", "scan_delay_max_ms", "Scan-Verzögerung"),
        ("action_delay_min_ms", "action_delay_max_ms", "Aktions-Verzögerung"),
        ("movement_speed_min", "movement_speed_max", "Bewegungsgeschwindigkeit"),
        ("reaction_time_min_ms", "reaction_time_max_ms", "Reaktionszeit"),
        ("click_duration_min_ms", "click_duration_max_ms", "Klickdauer"),
        ("work_minutes_min", "work_minutes_max", "Arbeitszeit"),
        ("pause_seconds_min", "pause_seconds_max", "Pausendauer"),
        ("template_scale_min", "template_scale_max", "Template-Skala"),
        ("circle_radius_min_frac", "circle_radius_max_frac", "Zielkreis-Radius"),
    ]

    def __init__(self, path: str = DEFAULT_CONFIG_PATH, auto_load: bool = True):
        """
        Creates a ToolConfig object.

        Args:
            path (str, optional): Path of the JSON config file. Defaults to
                DEFAULT_CONFIG_PATH ("tool_config.json").
            auto_load (bool, optional): If the config should be loaded from
                disk immediately (or created with defaults if missing).
                Defaults to True.
        """
        self.__path = path
        # Start from a fully valid default configuration.
        self.__values: Dict[str, Dict[str, Any]] = self.__build_defaults()

        if auto_load:
            self.load()

    def __build_defaults(self) -> Dict[str, Dict[str, Any]]:
        """
        Builds a configuration dict filled with the default value of every
        setting defined in the schema.

        Returns:
            Dict[str, Dict[str, Any]]: section -> {key: default_value}
        """
        defaults: Dict[str, Dict[str, Any]] = {}
        for section, settings in self.SCHEMA.items():
            defaults[section] = {}
            for key, spec in settings.items():
                defaults[section][key] = spec["default"]
        return defaults

    def __find_spec(self, key: str):
        """
        Finds the schema entry (and its section) for a setting key.

        Args:
            key (str): The setting name, e.g. "log_level".

        Returns:
            Tuple[str, dict]: (section, spec)

        Raises:
            KeyError: If the key is not part of the schema.
        """
        for section, settings in self.SCHEMA.items():
            if key in settings:
                return section, settings[key]
        raise KeyError(f"Unknown setting: {key}")

    def __coerce(self, spec: Dict[str, Any], value: Any) -> Any:
        """
        Tries to coerce a raw value (e.g. read from JSON or typed by the user)
        into the type expected by the schema entry.

        Args:
            spec (dict): The schema entry of the setting.
            value (Any): The raw value.

        Returns:
            Any: The coerced value.

        Raises:
            ValueError: If the value can not be coerced into the target type.
        """
        vtype = spec["type"]
        if vtype == "bool":
            if isinstance(value, bool):
                return value
            # Accept common textual/int representations.
            text = str(value).strip().lower()
            if text in ("true", "1", "yes", "y", "ja"):
                return True
            if text in ("false", "0", "no", "n", "nein"):
                return False
            raise ValueError(f"'{value}' is not a valid boolean")
        if vtype == "int":
            return int(value)
        if vtype == "float":
            return float(value)
        # "choice" and "str" keep their textual value.
        return str(value)

    def __validate(self, spec: Dict[str, Any], value: Any) -> Any:
        """
        Coerces and validates a value against a schema entry.

        Choice values must be one of the allowed choices, numeric values must
        lie within [min, max].

        Args:
            spec (dict): The schema entry of the setting.
            value (Any): The raw value to validate.

        Returns:
            Any: The validated (and coerced) value.

        Raises:
            ValueError: If the value is invalid for this setting.
        """
        value = self.__coerce(spec, value)

        if spec["type"] == "choice":
            if value not in spec["choices"]:
                raise ValueError(
                    f"'{value}' is not allowed, choose one of {spec['choices']}")

        if spec["type"] in ("int", "float"):
            if spec["min"] is not None and value < spec["min"]:
                raise ValueError(
                    f"{value} is below the minimum of {spec['min']}")
            if spec["max"] is not None and value > spec["max"]:
                raise ValueError(
                    f"{value} is above the maximum of {spec['max']}")

        return value

    def get(self, key: str) -> Any:
        """
        Returns the current value of a setting.

        Args:
            key (str): The setting name.

        Returns:
            Any: The current value.
        """
        section, _ = self.__find_spec(key)
        return self.__values[section][key]

    def set(self, key: str, value: Any) -> None:
        """
        Validates and sets a setting value (in memory, call save() to persist).

        Args:
            key (str): The setting name.
            value (Any): The new value.

        Raises:
            ValueError: If the value is invalid for this setting.
        """
        section, spec = self.__find_spec(key)
        self.__values[section][key] = self.__validate(spec, value)
        _logger.debug(f"Set {key} = {self.__values[section][key]}")

    def get_spec(self, key: str) -> Dict[str, Any]:
        """
        Returns the schema entry (default, min, max, desc, ...) of a setting.

        Args:
            key (str): The setting name.

        Returns:
            Dict[str, Any]: The schema entry.
        """
        _, spec = self.__find_spec(key)
        return spec

    def as_dict(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a deep-ish copy of the current configuration values.

        Returns:
            Dict[str, Dict[str, Any]]: section -> {key: value}
        """
        return {section: dict(values) for section, values in self.__values.items()}

    def check_pairs(self) -> list:
        """
        Checks all min/max setting pairs for plausibility (min <= max).

        Returns:
            list: A list of human readable problem strings, empty if all pairs
                are consistent.
        """
        problems = []
        for min_key, max_key, label in self.PAIRS:
            vmin = self.get(min_key)
            vmax = self.get(max_key)
            if vmin > vmax:
                problems.append(
                    f"{label}: Minimum ({min_key}={vmin}) darf nicht groesser "
                    f"als Maximum ({max_key}={vmax}) sein")
        return problems

    def load(self) -> None:
        """
        Loads the configuration from the JSON file.

        Every value is validated against the schema; invalid or missing values
        fall back to their default. Unknown keys/sections in the file are
        ignored. If the file does not exist it is created with defaults.
        """
        if not os.path.exists(self.__path):
            _logger.info(
                f"Config file '{self.__path}' not found, creating defaults")
            self.__values = self.__build_defaults()
            self.save()
            return

        try:
            with open(self.__path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning(
                f"Could not read config '{self.__path}' ({e}), using defaults")
            self.__values = self.__build_defaults()
            self.save()
            return

        # Rebuild from defaults, then overlay valid stored values.
        values = self.__build_defaults()
        for section, settings in self.SCHEMA.items():
            stored_section = raw.get(section, {})
            if not isinstance(stored_section, dict):
                _logger.warning(
                    f"Section '{section}' is malformed, using defaults")
                continue
            for key, spec in settings.items():
                if key not in stored_section:
                    continue
                try:
                    values[section][key] = self.__validate(
                        spec, stored_section[key])
                except (ValueError, TypeError) as e:
                    _logger.warning(
                        f"Invalid value for '{key}' ({e}), using default "
                        f"{spec['default']}")

        self.__values = values

        # A hand-edited file may contain an inconsistent min/max pair. Warn but
        # keep the values (loading must never crash); save() will refuse to
        # write such a state.
        for problem in self.check_pairs():
            _logger.warning(f"Inconsistent config: {problem}")

        _logger.info(f"Loaded config from '{self.__path}'")

    def save(self) -> None:
        """
        Persists the current configuration to the JSON file.

        Raises:
            ValueError: If a min/max pair is inconsistent (min > max). Nothing
                is written in that case.
        """
        problems = self.check_pairs()
        if problems:
            raise ValueError("; ".join(problems))

        try:
            with open(self.__path, "w", encoding="utf-8") as f:
                json.dump(self.__values, f, indent=4, ensure_ascii=False)
            _logger.info(f"Saved config to '{self.__path}'")
        except OSError as e:
            _logger.error(f"Could not write config '{self.__path}': {e}")
            raise

    def reset(self) -> None:
        """
        Resets all settings to their default value (in memory, call save() to
        persist).
        """
        self.__values = self.__build_defaults()
        _logger.info("Config reset to defaults")


if __name__ == "__main__":
    # Small manual check: create/load the config and print it.
    logging.basicConfig(level=logging.INFO)
    cfg = ToolConfig()
    print(json.dumps(cfg.as_dict(), indent=4, ensure_ascii=False))
