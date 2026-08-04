"""
Simple input()-based CLI menu to view and change the tool settings.

Run with:  python config_ui.py  [--config tool_config.json]

The menu lists every setting grouped by section (GENERAL, DETECTION, OUTPUT),
lets the user pick a setting, shows its description / allowed range and asks
for a new value. Values are validated through ToolConfig before they are
stored, so out-of-range or wrong-typed input is rejected with a message
instead of being saved.
"""

import argparse
from config import ToolConfig


def _format_value(value) -> str:
    """
    Formats a value for display in the menu.

    Args:
        value: The setting value.

    Returns:
        str: A readable representation ("An"/"Aus" for booleans).
    """
    if isinstance(value, bool):
        return "An" if value else "Aus"
    return str(value)


def _allowed_hint(spec: dict) -> str:
    """
    Builds a short hint describing the allowed values of a setting.

    Args:
        spec (dict): The schema entry of the setting.

    Returns:
        str: e.g. "Auswahl: DEBUG/INFO/..." or "Bereich: 0.5 - 1.0".
    """
    if spec["type"] == "choice":
        return "Auswahl: " + " / ".join(spec["choices"])
    if spec["type"] == "bool":
        return "An / Aus"
    if spec["type"] in ("int", "float"):
        return f"Bereich: {spec['min']} - {spec['max']}"
    return "freier Text"


def _build_index(config: ToolConfig):
    """
    Builds a flat, numbered index of all settings for the menu.

    Args:
        config (ToolConfig): The configuration object.

    Returns:
        list: A list of (number, section, key) tuples.
    """
    index = []
    number = 1
    for section, settings in config.SCHEMA.items():
        for key in settings:
            index.append((number, section, key))
            number += 1
    return index


def _print_menu(config: ToolConfig, index) -> None:
    """
    Prints the full settings menu with current values.

    Args:
        config (ToolConfig): The configuration object.
        index (list): The numbered index from _build_index.
    """
    print("\n" + "=" * 60)
    print("  VIDEO-TOOL EINSTELLUNGEN")
    print("=" * 60)

    current_section = None
    for number, section, key in index:
        if section != current_section:
            print(f"\n--- {section} ---")
            current_section = section
        spec = config.get_spec(key)
        value = config.get(key)
        print(f"  [{number:>2}] {key:<26} = {_format_value(value):<10} "
              f"({spec['desc']})")

    print("\n--- AKTIONEN ---")
    print("  [ s] Speichern")
    print("  [ r] Auf Standardwerte zuruecksetzen")
    print("  [ q] Beenden")
    print("=" * 60)


def _edit_setting(config: ToolConfig, section: str, key: str) -> None:
    """
    Asks the user for a new value for a single setting and applies it.

    Args:
        config (ToolConfig): The configuration object.
        section (str): The section the setting belongs to.
        key (str): The setting name.
    """
    spec = config.get_spec(key)
    current = config.get(key)

    print(f"\nEinstellung: {key}  ({section})")
    print(f"  Beschreibung : {spec['desc']}")
    print(f"  Aktuell      : {_format_value(current)}")
    print(f"  Standard     : {_format_value(spec['default'])}")
    print(f"  Erlaubt      : {_allowed_hint(spec)}")

    raw = input("Neuer Wert (leer = unveraendert): ").strip()
    if raw == "":
        print("-> Unveraendert.")
        return

    try:
        config.set(key, raw)
        print(f"-> Gesetzt: {key} = {_format_value(config.get(key))}")
    except (ValueError, TypeError) as e:
        print(f"-> Ungueltig: {e}")


def run_menu(path: str) -> None:
    """
    Runs the interactive configuration menu loop.

    Args:
        path (str): Path of the JSON config file to edit.
    """
    config = ToolConfig(path)
    index = _build_index(config)
    dirty = False  # True if there are unsaved changes.

    while True:
        _print_menu(config, index)
        choice = input("Auswahl: ").strip().lower()

        if choice == "q":
            if dirty:
                confirm = input(
                    "Ungespeicherte Aenderungen. Trotzdem beenden? (j/N): "
                ).strip().lower()
                if confirm not in ("j", "ja", "y", "yes"):
                    continue
            print("Beendet.")
            return

        if choice == "s":
            try:
                config.save()
            except ValueError as e:
                print(f"-> NICHT gespeichert (unplausible Werte): {e}")
                continue
            dirty = False
            print("-> Gespeichert.")
            continue

        if choice == "r":
            config.reset()
            dirty = True
            print("-> Auf Standardwerte zurueckgesetzt (noch nicht gespeichert).")
            continue

        # Otherwise expect a setting number.
        if not choice.isdigit():
            print("-> Bitte eine Nummer oder s/r/q eingeben.")
            continue

        selected = int(choice)
        match = next((item for item in index if item[0] == selected), None)
        if match is None:
            print("-> Unbekannte Nummer.")
            continue

        _, section, key = match
        before = config.get(key)
        _edit_setting(config, section, key)
        if config.get(key) != before:
            dirty = True
            # Immediately warn if this change made a min/max pair inconsistent.
            for problem in config.check_pairs():
                print(f"-> WARNUNG: {problem}")


def main():
    parser = argparse.ArgumentParser(
        description="CLI-Menue zum Bearbeiten der Video-Tool-Einstellungen")
    parser.add_argument("--config", default="tool_config.json",
                        help="Pfad zur Konfigurationsdatei")
    args = parser.parse_args()

    try:
        run_menu(args.config)
    except (KeyboardInterrupt, EOFError):
        print("\nAbgebrochen.")


if __name__ == "__main__":
    main()
