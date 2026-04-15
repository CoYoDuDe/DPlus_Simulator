# TODO – Zündplus-Integration für DPlus_Simulator

## Ziel

Der DPlus-Simulator soll optional zusätzlich ein **Zündplus-Signal** auswerten.

Wichtig:
- Das Zündplus-Feature ist **optional**
- Der DPlus-Simulator muss **ohne Zusatzhardware weiter wie bisher funktionieren**
- **Nur wenn** der Nutzer den neuen Schalter **„Zündplus verwenden“** aktiviert, wird ein GPIO-Eingang benötigt

---

## Grundverhalten

### Wenn `Zündplus verwenden = AUS`
Der DPlus-Simulator arbeitet exakt wie bisher:

- Einschalten bei `on_voltage`
- Ausschalten bei `off_voltage`
- Einschaltverzögerung über `on_delay_seconds`
- Ausschaltverzögerung über `off_delay_seconds`

---

### Wenn `Zündplus verwenden = AN`
Dann gilt folgende Logik:

#### Einschalten
Nur wenn:
- Zündung **an**
- und Spannung `>= on_voltage`
- und `on_delay_seconds` abgelaufen ist

#### Ausschalten
Wenn Zündung **aus**:
- DPlus-Signal **sofort aus**
- ohne `off_voltage`
- ohne `off_delay_seconds`

#### Verhalten bei laufender Zündung
Solange Zündung **an** ist:
- `off_voltage` wird ignoriert
- `off_delay_seconds` wird ignoriert

Ziel:
Der Booster soll bei kurzen Spannungsabfällen im Leerlauf / beim Anhalten **nicht** unnötig ausgehen.

---

## Not-Aus bei extremer Unterspannung

Auch bei aktiver Zündung soll es eine Sicherheitsabschaltung geben.

### Neue Logik
Wenn:
- `Zündplus verwenden = AN`
- Zündung **an**
- Spannung `< emergency_off_voltage`
- für länger als `emergency_off_delay_seconds`

Dann:
- Ausgang AUS

### Vorgeschlagene Defaultwerte
- `emergency_off_voltage = 11.8`
- `emergency_off_delay_seconds = 2.0`

Diese Werte müssen im UI einstellbar sein.

---

## Neue Einstellungen / Settings

Neue Settings unter `/Settings/Devices/DPlusSim/...`

### Pflicht
- `UseIgnition`
  - Typ: bool
  - Default: False
  - Bedeutung: Aktiviert die Zündplus-Logik

- `IgnitionGpioPin`
  - Typ: int
  - Default: z. B. 17
  - Bedeutung: GPIO-Pin für Zündplus

- `IgnitionActiveHigh`
  - Typ: bool
  - Default: True
  - Bedeutung:
    - True = HIGH = Zündung an
    - False = LOW = Zündung an

- `EmergencyOffVoltage`
  - Typ: float
  - Default: 11.8

- `EmergencyOffDelaySec`
  - Typ: float
  - Default: 2.0

### Optional / diagnostisch
- `IgnitionState`
  - Status (0 / 1)

---

## UI-Änderungen

## Neuer Hauptschalter
- **Zündplus verwenden**
- Default: AUS

Zusätzliche Felder:
- GPIO Pin
- Signal invertieren (ActiveHigh)

### Hinweistext im UI
> Optionales Feature. GPIO darf nur mit 3.3V betrieben werden. Zündplus (12–14,5 V) muss über geeignete Schutzbeschaltung angepasst werden.

---

## Sichtbarkeit der Felder

### Wenn `Zündplus verwenden = AUS`
anzeigen:
- Einschaltspannung
- Ausschaltspannung
- Einschaltverzögerung
- Ausschaltverzögerung

### Wenn `Zündplus verwenden = AN`
anzeigen:
- Einschaltspannung
- Einschaltverzögerung
- Not-Aus-Unterspannung
- Not-Aus-Verzögerung
- GPIO Pin
- ActiveHigh

ausblenden:
- Ausschaltspannung
- Ausschaltverzögerung

---

## Laufzeitverhalten / Fehlerbehandlung

### Wenn `UseIgnition = false`
- Verhalten wie bisher

### Wenn `UseIgnition = true`
- GPIO wird gelesen

#### Fehlerfälle
- GPIO nicht lesbar:
  - kein Crash
  - als Zündung AUS behandeln
  - Log-Eintrag erzeugen

---

## Hardware

Zündplus ist 12–14,5 V und darf **nicht direkt** an GPIO angeschlossen werden.

Empfohlene Lösungen:

- Optokoppler (empfohlen)
- Transistorstufe
- Relais (Signaltrennung)

GPIO erwartet:
- max. 3.3V
- sauberes digitales Signal

---

## Anpassungen im Code

## 1. Settings erweitern
- `use_ignition`
- `ignition_gpio_pin`
- `ignition_active_high`
- `emergency_off_voltage`
- `emergency_off_delay_seconds`

## 2. Status erweitern
- `ignition_state`

## 3. GPIO-Reader implementieren
- Pin initialisieren
- Zustand lesen
- ggf. invertieren

## 4. SwitchLogic erweitern
- ohne Zündplus = unverändert
- mit Zündplus:
  - On nur bei `ignition_on && voltage_ok`
  - Off sofort bei `ignition_off`
  - `off_voltage` ignorieren
  - Not-Aus separat

## 5. Logging
- Zündung erkannt / verloren
- Not-Aus aktiv

---

## Testfälle

## Ohne Zündplus
- Verhalten unverändert

## Mit Zündplus

### Einschalten
- Zündung aus + hohe Spannung -> darf NICHT einschalten
- Zündung an + zu niedrige Spannung -> darf NICHT einschalten
- Zündung an + hohe Spannung -> darf einschalten

### Ausschalten
- Zündung an + Spannung fällt -> bleibt EIN
- Zündung aus -> sofort AUS

### Not-Aus
- kurz unter Schwelle -> bleibt EIN
- länger unter Schwelle -> AUS

### Fehlerfall
- GPIO fehlt -> bleibt AUS, kein Crash

---

## Wichtige Randbedingungen

- GPIO ist Standardlösung
- Feature bleibt optional

---

## Empfehlung zur Umsetzung

1. Settings + UI erweitern
2. GPIO einlesen
3. Logik integrieren
4. Tests im Fahrzeug
