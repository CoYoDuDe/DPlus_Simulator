# DPlus Simulator

## Projektbeschreibung
Der DPlus Simulator stellt eine Software-Komponente bereit, mit der die D+-Signalisierung für Victron-Geräte simuliert werden kann. Er ermöglicht automatisierte Tests von Energie- und Bordnetzsystemen, ohne dass ein realer Generator oder eine Lichtmaschine angeschlossen sein muss. Die Anwendung kann sowohl lokal auf einem Testsystem als auch auf einem GX-Gerät betrieben werden und unterstützt das Zusammenspiel mit dem Victron Venus OS.

## Funktionsumfang
- Simulation des D+-Signals über konfigurierbare Ansteuerung des Ausgangstreibers.
- Frei definierbare Ein- und Ausschaltbedingungen inklusive optionaler Hysterese und Verzögerungen.
- Verwaltung der Einstellungen über das Victron `com.victronenergy.settings`-Objekt.
- Direkte Registrierung der Einstellungswerte über das Victron `SettingsDevice`, inklusive Live-Synchronisation mit dem Dienst.
- Integration in das Venus OS durch Bereitstellung eines Services, der im Victron DBus sichtbar ist.
- Optionaler Zündplus-Eingang als weitere Einschaltbedingung sowie ein erzwungener Dauerbetrieb.
- Logging der Installations- und Laufzeitereignisse über den PackageManager sowie lokale Logdateien.

## Installation
Die Installation erfolgt über den SetupHelper in Kombination mit dem Victron PackageManager:
1. Kopieren Sie das Paket auf das GX-Gerät (z. B. per SCP).
2. Öffnen Sie den SetupHelper und wählen Sie die Option **PackageManager**.
3. Installieren Sie das Paket `dplus-simulator` und bestätigen Sie den Installationsdialog.
4. Überprüfen Sie das PackageManager-Log, um den erfolgreichen Abschluss der Installation zu verifizieren.

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
| `ForceOn` | Erzwingt ein dauerhaft aktives Ausgangssignal. |
| `StatusPublishInterval` | Aktualisierungsintervall der Statusmeldungen. |
| `ServicePath` | D-Bus-Service, aus dem die Batteriespannung gelesen wird. |
| `VoltagePath` | Objektpfad des Spannungswertes innerhalb des Dienstes. |

Alle Werte lassen sich über den DBus-Explorer oder per `dbus-spy` anpassen. Änderungen werden sofort vom Dienst übernommen und – dank `SettingsDevice` – dauerhaft im `com.victronenergy.settings`-Baum hinterlegt.

### Statusinformationen
Der bereitgestellte DBus-Service `com.coyodude.dplussim` publiziert neben dem bisherigen Status zusätzliche Informationen:
- `effective_on_voltage` / `effective_off_voltage`: aktuell verwendete Schwellenwerte unter Berücksichtigung der Hysterese.
- `ignition_state` und `ignition_enabled`: Zustand und Nutzung des Zündplus-Eingangs.
- `allow_on`: Gibt an, ob die Einschaltbedingungen aktuell erfüllt sind.
- `force_on` / `force_on_active`: Konfiguration und tatsächlicher Einsatz des erzwungenen Betriebs.

Damit lassen sich die Entscheidungen des Reglers transparent nachverfolgen.

## Hardware-Verdrahtung
- **Zündplus-Eingang**: Verwenden Sie einen Spannungsteiler oder einen Optokoppler, um das Eingangssignal auf das zulässige Spannungsniveau des GX-Geräts zu bringen.
- **Ausgangstreiber**: Schalten Sie das simulierte D+-Signal über ein Relais oder einen MOSFET, um die angeschlossenen Verbraucher galvanisch zu trennen und die notwendige Strombelastbarkeit sicherzustellen.
- Achten Sie auf saubere Masseverbindungen und ausreichend dimensionierte Leitungen.

## Schutzmaßnahmen
- Verwenden Sie Schutzbeschaltungen (Freilaufdioden, Sicherungen), um Spannungsspitzen beim Schalten induktiver Lasten abzufangen.
- Legen Sie einen Überspannungsschutz am Eingang an, um das GX-Gerät vor transienten Ereignissen zu schützen.

## Betrieb und Log-Beobachtung
- Aktivieren Sie die Simulation über den entsprechenden DBus-Schlüssel oder die GX-Geräteoberfläche.
- Beobachten Sie das PackageManager-Log (`/var/log/PackageManager.log`), um Installations- und Update-Ereignisse zu verfolgen.
- Zusätzliche Laufzeitinformationen finden Sie in den Anwendungs-Logs unter `/var/log/dplus-simulator/`.

## Troubleshooting
| Problem | Mögliche Ursache | Lösung |
|---------|------------------|--------|
| Simulation startet nicht | Paket nicht installiert oder Dienst nicht aktiv | PackageManager-Log prüfen, Dienst neu starten (`svc -t dplus-simulator`) |
| Kein Ausgangssignal | Falsche Hardware-Verdrahtung oder fehlender Ausgangstreiber | Verkabelung prüfen, Relais/MOSFET auf Funktion testen |
| Fehlende DBus-Einträge | Service nicht registriert | Systemlog (`journalctl -u dplus-simulator`) prüfen |

## Tests
- Manuelle Funktionsprüfung über den DBus-Explorer.
- Überwachung der Ausgangssignale mit einem Multimeter oder Oszilloskop.

## Bekannte Einschränkungen
- Keine native Unterstützung für alternative Kommunikationsbusse.
- Abhängigkeit vom Victron Venus OS in der aktuellen Version.

## Lizenz
Dieses Projekt steht unter der MIT-Lizenz. Details finden Sie in der Datei `LICENSE`.
