# Release Notes

## Unveröffentlicht

### Hinzugefügt
- Preflight-Prüfung im Installer stellt sicher, dass SetupHelper ab Version 8.10, `python3` und das
  Python-Modul `dbus-next` vorhanden sind, bevor die Installation startet.

### Geändert
- `packageDependencies` folgt nun dem SetupHelper-Format für Paketkonflikte und bleibt bewusst leer,
  da der DPlus Simulator keine zwingenden Paketabhängigkeiten erzwingt.
- Installer signalisiert SetupHelper nach Installations-, Deinstallations- und Statusläufen nun explizit über `endScript`, ob Dateien, Dienste oder D-Bus-Settings aktualisiert wurden; dadurch greifen automatische GUI-Neustarts bzw. Reboot-Aufforderungen, während eine Fallback-Implementierung lokale Tests weiterhin ohne SetupHelper ermöglicht.
