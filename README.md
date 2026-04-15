# DPlus Simulator

D+ Simulator ist ein SetupHelper-Paket fuer Venus OS. Es installiert einen Dienst zur Simulation eines D+-Signals und bindet eine Einstellungsseite ins alte Venus-GUI-v1 ein.

## Voraussetzungen

- [SetupHelper](https://github.com/kwindrem/SetupHelper) von [kwindrem](https://github.com/kwindrem) aktuell installiert

# DPlus Simulator

D+ Simulator ist ein SetupHelper-Paket für Venus OS.  
Es simuliert ein D+-Signal abhängig von der Batteriespannung.

## Voraussetzungen

- SetupHelper installiert
- Eine Batteriespannung auf dem Victron-D-Bus (z. B. BMV oder SmartShunt)

## Installation

Repository im SetupHelper als Custom-Paket eintragen und über den PackageManager installieren.

## Zündplus (optional)

Optional kann ein Zündplus-Signal berücksichtigt werden.

Wenn aktiviert:
- Einschalten nur bei:
  - Spannung >= `OnVoltage`
  - und Zündung AN
- Ausschalten:
  - Zündung AUS → sofort AUS
- Während Zündung AN:
  - `OffVoltage` wird ignoriert

Not-Aus:
- Bei sehr niedriger Spannung (`EmergencyOffVoltage`)
- mit kurzer Verzögerung (`EmergencyOffDelaySec`)

## Hinweise

- Der Dienst benötigt eine gültige Spannungsquelle auf dem D-Bus
- Ohne Spannung arbeitet der Simulator nicht
- Manuelle Steuerung im GUI möglich
- BMV-Relay muss auf „Manuell“ stehen, wenn es verwendet wird

## Empfohlene Startwerte

12V-System:
- `OnVoltage`: 13.2
- `OffVoltage`: 12.8

24V-System:
- `OnVoltage`: 26.4
- `OffVoltage`: 25.6
