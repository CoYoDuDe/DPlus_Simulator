# TODO – Zündplus-Integration für DPlus_Simulator

## Ziel

Der DPlus-Simulator soll optional zusätzlich ein **Zündplus-Signal** auswerten.

Wichtig:
- Das Zündplus-Feature ist **optional**
- Der DPlus-Simulator muss **ohne ExpanderPiSetup weiter wie bisher funktionieren**
- **Nur wenn** der Nutzer den neuen Schalter **„Zündplus verwenden“** aktiviert, wird eine zusätzliche Zündplus-Quelle benötigt

---

## Grundverhalten

### Wenn `Zündplus verwenden = AUS`
Der DPlus-Simulator arbeitet exakt wie bisher:

- Einschalten bei `on_voltage`
- Ausschalten bei `off_voltage`
- Einschaltverzögerung über `on_delay_seconds`
- Ausschaltverzögerung über `off_delay_seconds`

Keine Abhängigkeit von ExpanderPiSetup.

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

- `IgnitionService`
  - Typ: string
  - Default: leer oder vordefinierter ExpanderPi-Dienst
  - Bedeutung: D-Bus-Service der Zündplusquelle

- `IgnitionPath`
  - Typ: string
  - Default: leer oder vordefinierter Pfad
  - Bedeutung: D-Bus-Pfad der Zündplusquelle

- `EmergencyOffVoltage`
  - Typ: float
  - Default: 11.8
  - Bedeutung: Kritische Unterspannung bei aktiver Zündung

- `EmergencyOffDelaySec`
  - Typ: float
  - Default: 2.0
  - Bedeutung: Verzögerung für Not-Aus bei extremer Unterspannung

### Optional / diagnostisch
- `IgnitionAvailable`
  - Nur Status, nicht als persistente User-Einstellung
  - Zeigt an, ob die Zündplusquelle erreichbar ist

- `IgnitionState`
  - Nur Status
  - 0 / 1 bzw. False / True

---

## UI-Änderungen

## Neuer Hauptschalter
- **Zündplus verwenden**
- Default: AUS

### Hinweistext im UI
> Optionales Feature. Benötigt ExpanderPiSetup und geeignete Hardware zur Zündsignalerfassung. Das Zündsignal darf nicht direkt mit 12–14,5 V an den Eingang angeschlossen werden.

Zusatz:
> Ohne aktiviertes Zündplus läuft der DPlus-Simulator wie bisher rein spannungsbasiert.

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

ausblenden oder deaktivieren:
- Ausschaltspannung
- Ausschaltverzögerung

Wichtig:
Diese beiden Felder dürfen in diesem Modus nicht mehr als normale Ausschaltlogik missverstanden werden.

---

## Laufzeitverhalten / Fehlerbehandlung

### Wenn `UseIgnition = false`
- keine Zündplusquelle nötig
- keine Fehlermeldung wegen fehlender Ignition-Quelle
- Verhalten wie bisher

### Wenn `UseIgnition = true`
Dann muss der Dienst versuchen, die konfigurierte Zündplusquelle zu lesen.

#### Wenn Quelle vorhanden
- normal arbeiten

#### Wenn Quelle fehlt / nicht lesbar
- Dienst **nicht abstürzen**
- Status setzen:
  - `ignition_available = false`
  - sinnvolle Fehlermeldung im Status / Log
- Einschalten blockieren
- Ausgang bleibt aus

Wichtig:
Fehlende Ignition-Quelle darf nicht den gesamten DPlus-Dienst zerstören.

---

## D-Bus-Anbindung der Zündplusquelle

Der DPlus-Simulator soll **kein 12-V-Signal direkt messen**.

Er soll einen fertigen, sauberen D-Bus-Zustand lesen:

- `0` / `False` = Zündung aus
- `1` / `True` = Zündung an

Die eigentliche Signalerfassung macht ExpanderPiSetup bzw. dessen Hardware-/Service-Seite.

---

## Erwartete Schnittstelle zu ExpanderPiSetup

DPlus_Simulator soll eine konfigurierbare Quelle lesen, z. B.:

- Service: `com.victronenergy.expanderpi`
- Path: `/DPlusSimulator/Ignition`

oder eine andere endgültig definierte Kombination.

Wichtig ist nur:
- digital
- stabil
- eindeutig
- 0/1

---

## Anpassungen im Code

## 1. Settings erweitern
In `SETTINGS_DEFINITIONS` und `DEFAULT_SETTINGS` ergänzen:
- `use_ignition`
- `ignition_service`
- `ignition_path`
- `emergency_off_voltage`
- `emergency_off_delay_seconds`

## 2. Status erweitern
In `SimulatorStatus` ergänzen:
- `ignition_available`
- `ignition_state`
- `ignition_source`
- ggf. `ignition_message`

## 3. Zusätzlichen Reader für Zündplus bauen
Ähnlich wie bei der Spannungsquelle:
- D-Bus-Wert lesen
- bool interpretieren
- Fehler sauber behandeln

## 4. SwitchLogic erweitern
Neue Logikpfade:
- ohne Zündplus = alt
- mit Zündplus:
  - On nur bei `ignition_on && voltage_ok`
  - Off sofort bei `ignition_off`
  - `off_voltage` ignorieren
  - Not-Aus separat behandeln

## 5. Polling / Refresh integrieren
Bei aktivem Zündplus muss der Status regelmäßig aktualisiert werden.

## 6. Logging ergänzen
Beim Umschalten klar loggen:
- Zündung erkannt / verloren
- Not-Aus aktiv
- Ignition-Quelle nicht verfügbar

---

## README / Dokumentation

README ergänzen um:
- Erklärung des optionalen Zündplus-Features
- Hinweis, dass ExpanderPiSetup nur dafür nötig ist
- Erklärung des Verhaltens bei aktiviertem Zündplus
- Erklärung der Not-Aus-Unterspannung
- Hinweis auf erforderliche Hardwareanpassung

---

## Testfälle

## Ohne Zündplus
- Einschalten bei `on_voltage`
- Ausschalten bei `off_voltage`
- Verhalten identisch zum alten Stand

## Mit Zündplus
### Einschalten
- Zündung aus + hohe Spannung -> darf NICHT einschalten
- Zündung an + zu niedrige Spannung -> darf NICHT einschalten
- Zündung an + hohe Spannung -> darf einschalten

### Ausschalten
- Zündung an + Spannung fällt unter `off_voltage` -> darf NICHT ausschalten
- Zündung aus -> muss SOFORT ausschalten

### Not-Aus
- Zündung an + Spannung kurz unter Not-Aus-Schwelle (< Delay) -> darf NICHT ausschalten
- Zündung an + Spannung länger unter Schwelle -> muss ausschalten

### Fehlerfall
- `UseIgnition=true`, aber Quelle fehlt -> Dienst bleibt am Leben, Ausgang bleibt aus, Fehlerstatus sichtbar

---

## Wichtige Randbedingungen

- ExpanderPiSetup ist **optional**
- Normale DPlus-Funktion darf nie von ExpanderPiSetup abhängig werden
- Bei aktivem Zündplus soll der Nutzer im UI klar erkennen:
  - dass diese Zusatzfunktion aktiv ist
  - dass dafür Zusatzhardware / ExpanderPiSetup nötig ist

---

## Empfehlung zur Umsetzung

1. Zuerst Settings + Status + UI vorbereiten
2. Dann D-Bus-Ignition-Quelle definieren
3. Dann Logik implementieren
4. Dann README und UI-Texte ergänzen
5. Danach echte Fahrzeugtests mit:
   - Zündung an / aus
   - Spannungsabfall im Leerlauf
   - Not-Aus-Unterspannung
