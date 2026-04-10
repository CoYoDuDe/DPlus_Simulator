# Release Notes

## Unveroeffentlicht

### Geaendert
- Das `setup` wurde auf den normalen `SetupHelper`-Minimalstil zurueckgebaut. DPlus nutzt jetzt wie die funktionierenden Pakete direkt `IncludeHelpers` statt eigener Fallback- und Wrapper-Logik.
- `DbusSettingsList` liegt jetzt statisch im Paket und wird nicht mehr erst zur Laufzeit aus `settingsList` erzeugt.
- Die DPlus-QML verzichtet auf problematische Properties wie `font.*` und `inputMethodHints` und bleibt bei konservativen Venus-GUI-v1-Elementen.
- Das Service-Run-Skript nutzt auf Venus OS weiter den vorhandenen `velib_python`-Pfad und `dbus_fast` als asyncio-D-Bus-Backend.
