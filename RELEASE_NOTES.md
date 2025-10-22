# Release Notes

## Unveröffentlicht

### Hinzugefügt
- Preflight-Prüfung im Installer stellt sicher, dass SetupHelper ab Version 8.10, `python3` und das
  Python-Modul `dbus-next` vorhanden sind, bevor die Installation startet.

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
- Registrierung und Deregistrierung der D-Bus-Settings verwenden ausschließlich `addAllDbusSettings`, `removeAllDbusSettings` und `removeDbusSettings`. Die JSON-Payload wird zur Laufzeit erzeugt, kurzzeitig in `DbusSettingsList` abgelegt und nach erfolgreichem Helper-Aufruf wieder entfernt, wodurch der Ablauf mit den offiziellen SetupHelper-Beispielen identisch bleibt.

### Dokumentiert
- README erläutert die unterstützte SetupHelper-Version, beschreibt den temporären Umgang mit `DbusSettingsList` und führt alle D-Bus-Settings inklusive Typen sowie Standardwerten tabellarisch auf.
