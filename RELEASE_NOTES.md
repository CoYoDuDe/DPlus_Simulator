# Release Notes

## Unveröffentlicht

### Hinzugefügt
- Preflight-Prüfung im Installer stellt sicher, dass SetupHelper ab Version 8.10, `python3` und das
  Python-Modul `dbus-next` vorhanden sind, bevor die Installation startet.

### Geändert
- `packageDependencies` folgt nun dem SetupHelper-Format für Paketkonflikte und bleibt bewusst leer,
  da der DPlus Simulator keine zwingenden Paketabhängigkeiten erzwingt.
