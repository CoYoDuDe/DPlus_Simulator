# DPlus Simulator

D+ Simulator ist ein SetupHelper-Paket fuer Venus OS. Es installiert einen Dienst zur Simulation eines D+-Signals und bindet eine Einstellungsseite ins alte Venus-GUI-v1 ein.

## Voraussetzungen

- `SetupHelper` aktuell installiert
- `python3` verfuegbar
- Fuer `OutputMode=relay`: `gpiosetup` und `guimods`

## Installation

Repository im SetupHelper als Custom-Paket eintragen und ueber den PackageManager installieren.

Das Paket nutzt den offiziellen SetupHelper-Ablauf:

- `IncludeHelpers`
- `endScript INSTALL_FILES INSTALL_SERVICES ADD_DBUS_SETTINGS`
- FileSets fuer GUI-Dateien und Patch
- `DbusSettingsList` fuer die Settings-Registrierung
- leere `packageDependencies` werden nicht extra verarbeitet

## GUI

Die QML-Seite ist bewusst konservativ aufgebaut und nutzt nur Venus-kompatible GUI-v1-Elemente:

- `MbPage`
- `VisibleItemModel`
- `MbItemOptions`
- `MbEditBox`
- `MbSwitch`
- `VBusItem`

Es werden keine dynamischen `QtDBus`-/`Qt.createQmlObject`-Konstrukte verwendet.
Die Seite ist in einfache Untermenüs aufgeteilt, damit sie auf älteren Venus-GUI-Ständen robuster bleibt.

## Wichtige Settings

- `GpioPin`
- `TargetVoltage`
- `Hysteresis`
- `OnVoltage`
- `OffVoltage`
- `ActivationDelaySeconds`
- `DeactivationDelaySeconds`
- `OnDelaySec`
- `OffDelaySec`
- `UseIgnition`
- `IgnitionGpio`
- `IgnitionPull`
- `OutputMode`
- `RelayChannel`
- `ForceOn`
- `ForceOff`
- `StatusPublishInterval`
- `DbusBus`

`ServicePath` und `VoltagePath` werden vom Dienst automatisch gesetzt und im GUI nur angezeigt.

## Hinweise

- Der Dienst erwartet eine gueltige Starterspannungsquelle auf dem gewaehlten D-Bus.
- Ohne gueltige `/StarterVoltage`-Quelle startet der Simulator nicht produktiv.
- Im Relay-Modus uebernimmt der Dienst die Funktionszuweisung und Ruecksicherung des konfigurierten Relais.
- Der Dienst nutzt auf Venus OS den vorhandenen `dbus-python`-/`velib_python`-Stack; das Service-Run-Skript ergänzt dafuer bei Bedarf den bekannten `velib_python`-Pfad.
