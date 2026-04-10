# DPlus Simulator

D+ Simulator ist ein SetupHelper-Paket fuer Venus OS. Es installiert einen Dienst zur Simulation eines D+-Signals und bindet eine Einstellungsseite ins alte Venus-GUI-v1 ein.

## Voraussetzungen

- [SetupHelper](https://github.com/kwindrem/SetupHelper) von [kwindrem](https://github.com/kwindrem) aktuell installiert
- `python3` verfuegbar
- Fuer `OutputMode=relay`: `RpiGpioSetup` und `GuiMods`
- Venus OS mit vorhandenem `dbus_fast` sowie `dbus-python`/`velib_python`
- Eine verfuegbare Batteriespannung auf dem Victron-D-Bus, z. B. ueber BMV oder SmartShunt

Dieses Paket baut auf [SetupHelper](https://github.com/kwindrem/SetupHelper) von [kwindrem](https://github.com/kwindrem) auf.

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

- `Enabled`
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
- `VoltageSourceMode`
- `RelayChannel`
- `StatusPublishInterval`

`ServicePath` und `VoltagePath` werden bei `VoltageSourceMode=auto` automatisch gesetzt. Bei `VoltageSourceMode=manual` koennen sie im GUI fuer eine gezielte Spannungsquelle vorgegeben werden.

## Hinweise

- Der Dienst erwartet eine gueltige Starterspannungsquelle auf dem gewaehlten D-Bus.
- Ohne gueltige Batteriespannung auf dem Victron-D-Bus startet der Simulator nicht produktiv.
- Ueber `D+ Simulator aktiv` im GUI kann der Ausgang zu Testzwecken sauber ein- und ausgeschaltet werden, ohne die restlichen Einstellungen zu verlieren.
- Wenn mehrere Batteriespannungen vorhanden sind, kann die Spannungsquelle im GUI auf `Manuell` gestellt und ueber D-Bus-Dienst und Spannungspfad gezielt ausgewaehlt werden.
- Im Relay-Modus uebernimmt der Dienst die Funktionszuweisung und Ruecksicherung des konfigurierten Relais.
- Der Dienst nutzt auf Venus OS fuer den asynchronen D-Bus-Teil `dbus_fast` und fuer Settings/VeDbus den vorhandenen `dbus-python`-/`velib_python`-Stack.
- Der Standard ist `OutputMode=relay` mit dem letzten System-Relay-Kanal. Wenn keine passenden Relays ueber `RpiGpioSetup` vorhanden sind, kann im GUI auf `GPIO-Pin` umgestellt werden.
- Das Zündsignal ist optional. Wenn es verwendet werden soll, muss das Signal auf einen frei waehlbaren GPIO gefuehrt werden; im GUI werden dafuer `Zuendsignal verwenden`, `Zuend-GPIO` und `Zuend-Pull-Konfiguration` angeboten.
