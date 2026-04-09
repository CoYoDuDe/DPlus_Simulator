# FileSets

Dieser Ordner enthält alle Artefakte, die der SetupHelper benötigt, um das DPlus_Simulator-Add-on in Venus OS zu integrieren. Die Dateien sind nach ihrem Einsatzzweck gruppiert, damit die Paketgenerierung reproduzierbar bleibt.

## Dateilisten
- **`fileListVersionIndependent`** – listet alle versionsunabhängigen QML-Dateien auf, die unverändert auf das Zielsystem kopiert werden. Aktuell umfasst dies `PageSettingsDPlusSimulator.qml`, welche die D+ Simulator-Einstellungsseite bereitstellt.
- **`fileListPatched`** – führt Dateien auf, die per Patch angepasst werden. Der Eintrag `PageSettings.qml` verweist auf die GUI-Hauptseite, die um das D+ Simulator-Untermenü ergänzt wird.

## Versionsunabhängige Dateien (`VersionIndependent/`)
- `VersionIndependent/PageSettingsDPlusSimulator.qml` – QML-Oberfläche für das Einstellungsmenü des D+ Simulators.

## Patchquellen (`PatchSource/`)
- `PatchSource/PageSettings.qml.orig` – unveränderte Referenzdatei, dient als Grundlage für Diff-Prüfungen.
- `PatchSource/PageSettings.qml.patch` – Patch, der ein neues `MbSubMenu` mit Verlinkung auf `PageSettingsDPlusSimulator` einfügt, damit die Seite in den Venus-OS-Einstellungen erscheint.
- `PatchSource/PageSettings.qml` – erwartetes Ergebnis nach Anwendung des Patches, ermöglicht eine schnelle Sichtprüfung.

Die Kombination aus Dateilisten, QML-/JS-Quellen und Patch stellt sicher, dass der Installer sowohl neue Dateien verteilt als auch bestehende GUI-Komponenten konsistent erweitert.
