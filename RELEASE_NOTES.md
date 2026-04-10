# Release Notes

## Unveröffentlicht

### Hinzugefügt
- Preflight-Prüfung im Installer stellt sicher, dass SetupHelper ab Version 8.10 und `python3`
  vorhanden sind.
- FileSets-Dateilisten (`fileListVersionIndependent`, `fileListPatched`) beschreiben die Zielpfade für die
  QML-Oberfläche; das Setup-Skript triggert `checkFileSets`/`updateFileSets`, damit SetupHelper die GUI-Dateien
  und Patches verteilt.
- Neue Tests prüfen, dass bei Installations- und Deinstallationsläufen `updateFileSets` ausgeführt wird und die
  Artefakte in einem temporären Zielverzeichnis landen.

### Geändert
- Die DPlus-QML verzichtet jetzt auch auf `inputMethodHints`, weil diese Property auf dem Zielsystem bereits beim `SSHTunnel` zu einem White-Screen geführt hat und in `MbEditBox` nicht zuverlässig verfügbar ist.
- Der Dienst verwendet auf Venus OS jetzt eindeutig `dbus_fast` als asyncio-D-Bus-Backend. Die frühere Mehrfach-Fallback-Idee zu `dbus_next` wurde verworfen, weil auf dem Zielsystem `dbus_fast` bereits vorhanden ist.
- Die DPlus-GUI wurde nochmals vereinfacht und in stabile Unterseiten (`Ausgang`, `Eingänge`, `Schaltschwellen`, `Verzögerungen`, `Manuelle Steuerung`) aufgeteilt. Die problematischen Überschriften mit `font.*` sind entfernt.
- Die QML-Einstellungsseite verwendet jetzt ausschließlich konservative GUI-v1-Elemente (`Mb*`, `VBusItem`) ohne `QtDBus`, `Qt.createQmlObject` oder andere dynamische Laufzeit-Konstrukte. Die automatische Erkennung von `ServicePath`/`VoltagePath` verbleibt vollständig im Python-Dienst.
- `packageDependencies` bleibt leer, weil der `kwindrem`-SetupHelper dort nur Paketkonflikte
  zwischen SetupHelper-Add-ons auswertet; die zum Betrieb der D-Bus-Kommunikation benötigte
  Python-Bibliothek prüft der Installer selbst.
- Das Service-Run-Skript ergänzt nun auf Venus OS den bekannten `velib_python`-Pfad, damit der
  vorhandene `dbus-python`-/`SettingsDevice`-/`vedbus`-Stack direkt genutzt wird.
- Der Installer stößt die Installation der DPlus-GUI-Datei und des `PageSettings.qml`-Patches nun
  zusätzlich explizit über `updateActiveFile` an, damit die Helper-Ressourcen die QML-Seite auch auf
  Systemen mit inkonsistenter automatischer FileSet-Erkennung zuverlässig einhängen.
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
