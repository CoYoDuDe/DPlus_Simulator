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
- Registrierung und Deregistrierung der D-Bus-Settings erzeugen weiterhin die JSON-Payload, lassen `DbusSettingsList` jedoch bis `finalize_helper_session` bestehen, kopieren sie ins Installationsverzeichnis und überlassen `addAllDbusSettings`/`removeAllDbusSettings` dem `endScript`-Aufruf. Fällt `endScript` weg, greifen die bisherigen Direktaufrufe als Fallback.
- Tests zu `register_dbus_settings` und `unregister_dbus_settings` prüfen nun explizit, dass `DbusSettingsList` bis zum `endScript`-Aufruf bestehen bleibt und die Helper-Funktionen erst dort ausgelöst werden.

### Dokumentiert
- README erläutert die unterstützte SetupHelper-Version, erklärt die persistente `DbusSettingsList` für Reinstallationen und führt alle D-Bus-Settings inklusive Typen sowie Standardwerten tabellarisch auf.
