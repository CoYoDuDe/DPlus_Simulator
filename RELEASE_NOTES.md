# Release Notes

## Unveröffentlicht

### Hinzugefügt
- Preflight-Prüfung im Installer stellt sicher, dass SetupHelper ab Version 8.10, `python3` und das
  Python-Modul `dbus-next` vorhanden sind, bevor die Installation startet.
- FileSets-Dateilisten (`fileListVersionIndependent`, `fileListPatched`) beschreiben die Zielpfade für die
  QML-Oberfläche; das Setup-Skript triggert `checkFileSets`/`updateFileSets`, damit SetupHelper die GUI-Dateien
  und Patches verteilt.
- Neue Tests prüfen, dass bei Installations- und Deinstallationsläufen `updateFileSets` ausgeführt wird und die
  Artefakte in einem temporären Zielverzeichnis landen.

### Geändert
- `packageDependencies` folgt nun dem SetupHelper-Format für Paketkonflikte und bleibt bewusst leer,
  da der DPlus Simulator keine zwingenden Paketabhängigkeiten erzwingt.
- Der Installer ruft – sofern verfügbar – die offizielle `checkPackageDependencies`-Funktion des
  SetupHelper auf und protokolliert andernfalls lediglich das Überspringen der Prüfung, damit auch
  Installationen mit unveränderten Helper-Skripten störungsfrei durchlaufen.
- Die Abhängigkeitsprüfung läuft nur noch bei tatsächlichen Installationen; Deinstallations- und
  Statusläufe überspringen `checkPackageDependencies`, um Bereinigungen nicht zu blockieren.
- Installer beendet jetzt den Lauf sofort mit der vom SetupHelper gelieferten Meldung, sobald dieser
  `installFailed` oder eine abweichende `scriptAction` signalisiert – selbst bei Rückgabewert `0`.
- Installer signalisiert SetupHelper nach Installations-, Deinstallations- und Statusläufen nun explizit über `endScript`, ob Dateien, Dienste oder D-Bus-Settings aktualisiert wurden; dadurch greifen automatische GUI-Neustarts bzw. Reboot-Aufforderungen, während eine Fallback-Implementierung lokale Tests weiterhin ohne SetupHelper ermöglicht.
- Registrierung und Deregistrierung der D-Bus-Settings erzeugen weiterhin die JSON-Payload und halten `DbusSettingsList` bis `finalize_helper_session` vor. Die Deregistrierung ruft `removeAllDbusSettings` bzw. `removeDbusSettings` jetzt auch bei aktiver SetupHelper-API unmittelbar auf und signalisiert den Status nur noch über `dbusSettingsUpdated`.
- Die Deinstallation bricht ab, sobald das Entfernen der D-Bus-Settings fehlschlägt, damit keine inkonsistenten Reste zurückbleiben.
- Tests zu `register_dbus_settings` und `unregister_dbus_settings` erwarten nun direkte Aufrufe der Helper-Funktionen während `unregister_dbus_settings` und prüfen, dass Fehler zu einem kontrollierten Abbruch führen.

### Dokumentiert
- README erläutert die unterstützte SetupHelper-Version, erklärt die persistente `DbusSettingsList` für Reinstallationen und führt alle D-Bus-Settings inklusive Typen sowie Standardwerten tabellarisch auf.
