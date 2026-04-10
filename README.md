# DPlus Simulator

D+ Simulator ist ein SetupHelper-Paket fuer Venus OS. Es installiert einen Dienst zur Simulation eines D+-Signals und bindet eine Einstellungsseite ins alte Venus-GUI-v1 ein.

## Voraussetzungen

- `SetupHelper` von `kwindrem` aktuell installiert
- `python3` verfuegbar
- Fuer `OutputMode=relay`: `gpiosetup` und `guimods`
- Venus OS mit vorhandenem `dbus_fast` sowie `dbus-python`/`velib_python`

Dieses Paket baut auf dem SetupHelper-Projekt von `kwindrem` auf:

- `https://github.com/kwindrem/SetupHelper`

## Installation

Repository im SetupHelper als Custom-Paket eintragen und ueber den PackageManager installieren.

Das Paket nutzt den normalen SetupHelper-Standardpfad:

- `IncludeHelpers`
- FileSets fuer GUI-Dateien und Patch
- `DbusSettingsList` fuer die Settings-Registrierung
- Services aus `services/`

## GUI

Die QML-Seite ist bewusst konservativ aufgebaut und nutzt nur Venus-kompatible GUI-v1-Elemente:

- `MbPage`
- `VisibleItemModel`
- `MbItemOptions`
- `MbEditBox`
- `MbSwitch`
- `VBusItem`

Es werden keine dynamischen `QtDBus`-/`Qt.createQmlObject`-Konstrukte verwendet. Die Seite ist in einfache Untermenues aufgeteilt, damit sie auf aelteren Venus-GUI-Staenden robuster bleibt.

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
- Der Dienst nutzt auf Venus OS fuer den asynchronen D-Bus-Teil `dbus_fast` und fuer Settings/VeDbus den vorhandenen `dbus-python`-/`velib_python`-Stack.
