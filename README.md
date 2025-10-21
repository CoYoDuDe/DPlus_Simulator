# DPlus Simulator

## Projektbeschreibung
Der DPlus Simulator stellt eine Software-Komponente bereit, mit der die D+-Signalisierung für Victron-Geräte simuliert werden kann. Er ermöglicht automatisierte Tests von Energie- und Bordnetzsystemen, ohne dass ein realer Generator oder eine Lichtmaschine angeschlossen sein muss. Die Anwendung kann sowohl lokal auf einem Testsystem als auch auf einem GX-Gerät betrieben werden und unterstützt das Zusammenspiel mit dem Victron Venus OS.

## Funktionsumfang
- Simulation des D+-Signals über konfigurierbare Ansteuerung des Ausgangstreibers.
- Wahlweise Schaltung eines lokalen GPIO-Pins oder – bei aktivem gpiosetup/guimods – eines dort registrierten Relais.
- Frei definierbare Ein- und Ausschaltbedingungen inklusive optionaler Hysterese und Verzögerungen.
- Verwaltung der Einstellungen über das Victron `com.victronenergy.settings`-Objekt.
- Direkte Registrierung der Einstellungswerte über das Victron `SettingsDevice`, inklusive Live-Synchronisation mit dem Dienst.
- Integration in das Venus OS durch Bereitstellung eines Services, der im Victron DBus sichtbar ist.
- Optionaler Zündplus-Eingang mit konfigurierbarem Pull-Up/-Down als zusätzliche Einschaltbedingung.
- Erzwungener Dauerbetrieb über Force-On oder Force-Off.
- Logging der Installations- und Laufzeitereignisse über den PackageManager sowie lokale Logdateien.

## Installation
Die Installation erfolgt über den SetupHelper in Kombination mit dem Victron PackageManager:

> **Wichtig:** Der Dienst startet nur, wenn auf dem gewählten D-Bus ein Dienst die
> Starterspannung (`/StarterVoltage`) bereitstellt. Vorrangig wird `com.victronenergy.system`
> genutzt; fällt dieser Dienst aus, wird nach dem ersten passenden `com.victronenergy.battery.*`
> gesucht. Der gefundene Service und Pfad werden automatisch übernommen; Manipulationen an
> `ServicePath`/`VoltagePath` werden ignoriert. Fehlt eine gültige Quelle, beendet sich der
> Simulator kontrolliert, damit kein D+-Signal ohne reale Spannungsdaten erzeugt wird.

### Automatische Vorprüfungen des Installers

Vor dem eigentlichen Installationslauf führt das Setup-Skript eine Preflight-Prüfung durch.

### Abschlussaktionen nach Installation und Deinstallation

Nach jedem Installations-, Deinstallations- oder Statuslauf signalisiert das Setup-Skript dem SetupHelper jetzt explizit, welche Komponenten geändert wurden. Sobald Dateien, Dienste oder D-Bus-Settings betroffen sind, ruft das Skript `endScript` mit den Flags `INSTALL_FILES`, `INSTALL_SERVICE` und `ADD_DBUS_SETTINGS` auf. Der SetupHelper übernimmt daraufhin automatisch das Kopieren bzw. Entfernen der Dateien, das Aktualisieren des Dienstes sowie – falls erforderlich – GUI-Neustarts oder Reboot-Aufforderungen gemäß den offiziellen Richtlinien.

Wird das Skript ohne SetupHelper ausgeführt (z. B. in lokalen Testumgebungen), kommt ein Fallback zum Einsatz, der die bisherigen Log-Meldungen erzeugt, ohne zusätzliche Neustarts anzustoßen. Dadurch bleiben manuelle Tests und CI-Läufe weiterhin möglich.

Die Installation wird nur gestartet, wenn folgende Voraussetzungen erfüllt sind:

- **SetupHelper ab Version 8.10** – ältere Versionen werden mit einer klaren Fehlermeldung
  abgewiesen.
- **Verfügbares `python3`** – der Interpreter muss im Pfad auffindbar sein.
- **Python-Modul `dbus-next`** – wird per `python3 -c "import dbus_next"` geprüft.

Fehlt eine der Komponenten, bricht der Installer kontrolliert ab und verweist auf die erforderliche
Voraussetzung. Das `packageDependencies`-Dokument bleibt bewusst leer, da der DPlus Simulator keine
anderen SetupHelper-Pakete erzwingt. Sobald SetupHelper verfügbar ist, ruft das Skript die offizielle
`checkPackageDependencies`-Funktion mit dem hinterlegten Dokument auf. Läuft der Installer in einer
Umgebung ohne Helper-Skripte, wird lediglich informativ protokolliert, dass keine Konfliktprüfung
stattfindet. Optionale Erweiterungen (z. B. `gpiosetup`/`guimods` für den Relaisbetrieb) werden weiterhin
in der Anwendung dokumentiert, ohne die Installation zu blockieren.

### Konfigurationspfade
Die Konfiguration erfolgt über den Victron DBus (Service `com.victronenergy.settings`).
Die wichtigsten Schlüssel im Gerätekontext `Settings/Devices/DPlusSim` sind:

| Schlüssel | Beschreibung |
|-----------|---------------|
| `GpioPin` | GPIO-Ausgang, der das D+-Signal schaltet. |
| `TargetVoltage` / `Hysteresis` | Legacy-Parameter für symmetrische Schaltschwellen (werden weiterhin ausgewertet). |
| `OnVoltage` / `OffVoltage` | Getrennte Spannungen zum Ein- bzw. Ausschalten. |
| `OnDelaySec` / `OffDelaySec` | Verzögerungen für das Ein- und Ausschalten. |
| `UseIgnition` / `IgnitionGpio` | Aktiviert den Zündplus-Eingang und legt den Eingangspin fest. |
| `IgnitionPull` | Legt den Pull-Up/-Down-Modus für den Zündplus-Eingang fest (`up`, `down`, `none`). |
| `OutputMode` | Steuert, ob die Simulation einen GPIO (`gpio`) oder ein Relais (`relay`) nutzt. |
| `RelayChannel` | Ausgewählter gpiosetup-Relay-Kanal (z. B. `4brelays/0`), exklusiv vom Simulator belegt. |
| `ForceOn` / `ForceOff` | Erzwingt dauerhaft ein aktiviertes bzw. deaktiviertes Ausgangssignal. |
| `StatusPublishInterval` | Aktualisierungsintervall der Statusmeldungen. |
| `ServicePath` | Automatisch erkannter Dienst für die Starterspannung (wird vom Simulator gesetzt und kann nicht überschrieben werden). |
| `VoltagePath` | Vom Simulator gesetzter Starterspannungs-Pfad (`/StarterVoltage`, schreibgeschützt). |

Auf GX-Geräten steht auf der Einstellungsseite des D+-Simulators eine Auswahl aller
gefundenen Dienste mit Starterspannung zur Verfügung. Wird ein Eintrag ausgewählt, setzt
die Oberfläche `DbusBus`, `ServicePath` und `VoltagePath` automatisch auf die
Standardwerte des Dienstes. Die Felder werden ausschließlich zur Anzeige genutzt und
bleiben schreibgeschützt, damit der automatisch ermittelte Pfad nicht überschrieben wird.
Erkennt das System keinen Dienst mit `/StarterVoltage`, weist die Seite darauf hin, die
Verkabelung sowie die Konfiguration von System- oder BMV-/SmartShunt-Diensten zu prüfen
und bei anhaltenden Problemen den Support zu kontaktieren.

Alle Werte lassen sich über den DBus-Explorer oder per `dbus-spy` anpassen. Änderungen werden sofort vom Dienst übernommen und – dank `SettingsDevice` – dauerhaft im `com.victronenergy.settings`-Baum hinterlegt.

Der Simulator prüft beim Start zuerst `com.victronenergy.system` auf das Vorhandensein von `/StarterVoltage`. Ist dort kein Wert verfügbar, werden alle `com.victronenergy.battery.*`-Dienste durchsucht. Der erste Dienst mit gültiger Starterspannung wird übernommen; schlägt die Suche fehl, meldet der Dienst einen Fehlerzustand und stoppt.

### Abhängigkeiten der Ausgangsmodi
- **MOSFET-/GPIO-Modus (`OutputMode=gpio`)**: Funktioniert ohne weitere Zusatzpakete, solange der konfigurierte GPIO frei ist.
- **Relais-Modus (`OutputMode=relay`)**: Setzt voraus, dass die Zusatzpakete `gpiosetup` und `guimods` installiert und aktiv sind. Nur dann steht die Relaisverwaltung über `Settings/Relays/...` zur Verfügung. Sobald kein Relais zugewiesen ist oder gpiosetup nicht verfügbar ist, schaltet der Simulator automatisch auf den MOSFET-/GPIO-Modus zurück.

### Statusinformationen
Der bereitgestellte DBus-Service `com.coyodude.dplussim` publiziert neben dem bisherigen Status zusätzliche Informationen:
- `effective_on_voltage` / `effective_off_voltage`: aktuell verwendete Schwellenwerte unter Berücksichtigung der Hysterese.
- `output_mode` / `output_target` / `relay_channel`: zeigen, ob GPIO oder Relais geschaltet wird und welches Ziel adressiert ist.
- `ignition`: Enthält Zustand, Aktivierung, Pin und Pull-Mode des Zündplus-Eingangs.
- `allow_on` / `off_required`: Geben Auskunft über erfüllte Ein- und Ausschaltbedingungen.
- `conditions`: Aufgeschlüsselte Einzelergebnisse der Ein- bzw. Ausschaltlogik inklusive Hysterese.
- `force_mode`: Stellt konfigurierte und aktive Force-On/Force-Off-Zustände dar.
- `delays`: Liefert Pending-Status, verbleibende Verzögerungen sowie das nächste Umschaltereignis.

Damit lassen sich die Entscheidungen des Reglers transparent nachverfolgen.

## Hardware-Verdrahtung
- **Zündplus-Eingang**: Verwenden Sie einen Spannungsteiler oder einen Optokoppler, um das Eingangssignal auf das zulässige Spannungsniveau des GX-Geräts zu bringen.
- **Ausgangstreiber**: Schalten Sie das simulierte D+-Signal über ein Relais oder einen MOSFET, um die angeschlossenen Verbraucher galvanisch zu trennen und die notwendige Strombelastbarkeit sicherzustellen. Bei aktivem Relay-Modus sorgt der Simulator dafür, dass nicht gleichzeitig ein GPIO-Ausgang geschaltet bleibt.
- Achten Sie auf saubere Masseverbindungen und ausreichend dimensionierte Leitungen.

## Schutzmaßnahmen
- Verwenden Sie Schutzbeschaltungen (Freilaufdioden, Sicherungen), um Spannungsspitzen beim Schalten induktiver Lasten abzufangen.
- Legen Sie einen Überspannungsschutz am Eingang an, um das GX-Gerät vor transienten Ereignissen zu schützen.

## Betrieb und Log-Beobachtung
- Aktivieren Sie die Simulation über den entsprechenden DBus-Schlüssel oder die GX-Geräteoberfläche.
- Beobachten Sie das PackageManager-Log (`/var/log/PackageManager.log`), um Installations- und Update-Ereignisse zu verfolgen.
- Zusätzliche Laufzeitinformationen werden über das Python-Logging der Anwendung (`setup_logging` in `src/dplus_sim.py`) auf den Standardausgang geschrieben. Das zugehörige Log-Skript (`services/com.coyodude.dplussim/log/run`) leitet diese Ausgaben auf Zielsystemen wahlweise an den SetupHelper-Logpipe (`/data/SetupHelper/HelperResources/serviceLogPipe`) weiter oder – falls dieser nicht verfügbar ist – per `svlogd -tt` in das runit-Logverzeichnis des Dienstes (z. B. `/var/log/com.coyodude.dplussim/`). Verwenden Sie daher den SetupHelper-Logviewer bzw. lesen Sie die `current`-Datei im runit-Logordner, um Laufzeitereignisse nachzuverfolgen.

## Debug-Modus und Simulationstools
- Manuelle Spannungsinjektionen und die Sinus-Simulation sind ausschließlich für Entwicklungsszenarien vorgesehen. Setzen Sie hierfür die Umgebungsvariable `DPLUS_SIM_DEV_MODE=1` und starten Sie den Dienst zusätzlich mit `--enable-debug`.
- Ohne gesetzten Entwicklungsmodus blockiert der Dienst jede D-Bus-Anfrage an `InjectVoltageSample` zuverlässig.
- `--simulate-waveform` steht nur zur Verfügung, wenn `DPLUS_SIM_DEV_MODE` aktiv ist. Wird die Option ohne Entwicklungsmodus gesetzt, beendet der Argumentparser die Ausführung mit einer Fehlermeldung.
- In Produktivumgebungen darf `DPLUS_SIM_DEV_MODE` nicht gesetzt werden. Somit bleiben ausschließlich die produktiven Funktionen aktiv.

## Troubleshooting
| Problem | Mögliche Ursache | Lösung |
|---------|------------------|--------|
| Simulation startet nicht | Paket nicht installiert oder Dienst nicht aktiv | PackageManager-Log prüfen, Dienst neu starten (`svc -t dplus-simulator`) |
| Dienst stoppt sofort nach dem Start | Kein Dienst mit `/StarterVoltage` auf dem gewählten D-Bus gefunden oder Verbindung zur Spannungsquelle instabil | Verkabelung und D-Bus prüfen; sicherstellen, dass System- oder Batteriedienste die Starterspannung liefern, und Dienst erneut starten |
| Kein Ausgangssignal | Falsche Hardware-Verdrahtung oder fehlender Ausgangstreiber | Verkabelung prüfen, Relais/MOSFET auf Funktion testen |
| Fehlende DBus-Einträge | Service nicht registriert | Systemlog (`journalctl -u dplus-simulator`) prüfen |
