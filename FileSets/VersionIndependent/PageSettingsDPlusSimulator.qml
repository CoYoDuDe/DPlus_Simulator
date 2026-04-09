//// D+ simulator settings page

import QtQuick 2
import "utils.js" as Utils
import com.victron.velib 1.0

MbPage {
        id: root
        title: qsTr("D+ simulator")

        property string settingsPrefix: "com.victronenergy.settings/Settings/Devices/DPlusSim"

        property VBusItem outputModeItem: VBusItem { bind: settingsPath("/OutputMode") }
        property VBusItem useIgnitionItem: VBusItem { bind: settingsPath("/UseIgnition") }
        property VBusItem dbusBusStatusItem: VBusItem { bind: settingsPath("/DbusBus") }
        property VBusItem servicePathStatusItem: VBusItem { bind: settingsPath("/ServicePath") }
        property VBusItem voltagePathStatusItem: VBusItem { bind: settingsPath("/VoltagePath") }

        function settingsPath(suffix) {
                return Utils.path(settingsPrefix, suffix)
        }

        function textValue(item, fallback) {
                if (item && item.valid && item.value !== undefined && item.value !== null) {
                        var value = item.value.toString()
                        if (value.length)
                                return value
                }
                return fallback || ""
        }

        function numericValue(text) {
                var value = parseFloat(text)
                if (isNaN(value))
                        return undefined
                return value
        }

        function positiveDelayValue(text) {
                var value = numericValue(text)
                if (value === undefined)
                        return undefined
                if (value < 0.2)
                        value = 0.2
                return value
        }

        model: VisibleItemModel {
                MbItemText {
                        text: qsTr("Konfiguriere den virtuellen D+-Ausgang des D+ Simulator-Dienstes.")
                        wrapMode: Text.WordWrap
                }

                MbItemText {
                        text: qsTr("Ausgang")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbItemOptions {
                        id: outputModeOptions
                        description: qsTr("Ausgangsmodus")
                        item: outputModeItem
                        possibleValues: [
                                MbOption { description: qsTr("GPIO-Pin"); value: "gpio" },
                                MbOption { description: qsTr("Relay"); value: "relay" }
                        ]
                        writeAccessLevel: User.AccessInstaller
                }

                MbEditBox {
                        description: qsTr("GPIO-Pin")
                        item.bind: settingsPath("/GpioPin")
                        inputMethodHints: Qt.ImhDigitsOnly
                        maximumLength: 2
                        show: textValue(outputModeItem, "gpio") !== "relay"
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = parseInt(newValue, 10)
                                if (!isNaN(value))
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Relay-Kanal")
                        item.bind: settingsPath("/RelayChannel")
                        maximumLength: 40
                        overwriteMode: false
                        show: textValue(outputModeItem, "gpio") === "relay"
                        writeAccessLevel: User.AccessInstaller
                }

                MbItemText {
                        text: qsTr("Für den Relay-Modus muss gpiosetup die gewünschte Relay-Funktion bereits bereitstellen. Der D+ Simulator übernimmt nur die Einstellung des konfigurierten Kanalnamens.")
                        wrapMode: Text.WordWrap
                        show: textValue(outputModeItem, "gpio") === "relay"
                }

                MbItemText {
                        text: qsTr("Eingänge")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbSwitch {
                        id: useIgnitionSwitch
                        name: qsTr("Zündsignal verwenden")
                        item: useIgnitionItem
                        valueTrue: 1
                        valueFalse: 0
                        writeAccessLevel: User.AccessInstaller
                }

                MbEditBox {
                        description: qsTr("Zünd-GPIO")
                        item.bind: settingsPath("/IgnitionGpio")
                        inputMethodHints: Qt.ImhDigitsOnly
                        maximumLength: 2
                        show: useIgnitionItem.valid && useIgnitionItem.value
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = parseInt(newValue, 10)
                                if (!isNaN(value))
                                        item.setValue(value)
                        }
                }

                MbItemOptions {
                        description: qsTr("Zünd-Pull-Konfiguration")
                        bind: settingsPath("/IgnitionPull")
                        possibleValues: [
                                MbOption { description: qsTr("Floating"); value: "none" },
                                MbOption { description: qsTr("Pull-down"); value: "down" },
                                MbOption { description: qsTr("Pull-up"); value: "up" }
                        ]
                        show: useIgnitionItem.valid && useIgnitionItem.value
                        writeAccessLevel: User.AccessInstaller
                }

                MbItemOptions {
                        description: qsTr("D-Bus")
                        bind: settingsPath("/DbusBus")
                        possibleValues: [
                                MbOption { description: qsTr("System"); value: "system" },
                                MbOption { description: qsTr("Session"); value: "session" }
                        ]
                        writeAccessLevel: User.AccessInstaller
                }

                MbItemText {
                        text: qsTr("Die Spannungsquelle wird vom Dienst automatisch erkannt. ServicePath und VoltagePath werden vom Dienst gesetzt und sind im GUI nur zur Kontrolle sichtbar.")
                        wrapMode: Text.WordWrap
                }

                MbItemText {
                        text: qsTr("Erkannter Dienst: %1").arg(textValue(servicePathStatusItem, qsTr("noch nicht erkannt")))
                        wrapMode: Text.WordWrap
                }

                MbItemText {
                        text: qsTr("Spannungspfad: %1").arg(textValue(voltagePathStatusItem, "/StarterVoltage"))
                        wrapMode: Text.WordWrap
                }

                MbItemText {
                        text: qsTr("Aktiver D-Bus: %1").arg(textValue(dbusBusStatusItem, "system"))
                        wrapMode: Text.WordWrap
                }

                MbItemText {
                        text: qsTr("Schaltschwellen")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbEditBox {
                        description: qsTr("Zielspannung [V]")
                        item.bind: settingsPath("/TargetVoltage")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = numericValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Hysterese [V]")
                        item.bind: settingsPath("/Hysteresis")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 5
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = numericValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Einschaltspannung [V]")
                        item.bind: settingsPath("/OnVoltage")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 5
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = numericValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Ausschaltspannung [V]")
                        item.bind: settingsPath("/OffVoltage")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 5
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = numericValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbItemText {
                        text: qsTr("Verzögerungen")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbEditBox {
                        description: qsTr("Aktivierungsverzögerung [s]")
                        item.bind: settingsPath("/ActivationDelaySeconds")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = positiveDelayValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Deaktivierungsverzögerung [s]")
                        item.bind: settingsPath("/DeactivationDelaySeconds")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = positiveDelayValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Einschaltverzögerung [s]")
                        item.bind: settingsPath("/OnDelaySec")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = positiveDelayValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbEditBox {
                        description: qsTr("Ausschaltverzögerung [s]")
                        item.bind: settingsPath("/OffDelaySec")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = positiveDelayValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }

                MbItemText {
                        text: qsTr("Manuelle Steuerung")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbSwitch {
                        name: qsTr("Erzwungen EIN")
                        bind: settingsPath("/ForceOn")
                        valueTrue: 1
                        valueFalse: 0
                        writeAccessLevel: User.AccessInstaller
                }

                MbSwitch {
                        name: qsTr("Erzwungen AUS")
                        bind: settingsPath("/ForceOff")
                        valueTrue: 1
                        valueFalse: 0
                        writeAccessLevel: User.AccessInstaller
                }

                MbItemText {
                        text: qsTr("Dienstintegration")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbEditBox {
                        description: qsTr("Statusintervall [s]")
                        item.bind: settingsPath("/StatusPublishInterval")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        writeAccessLevel: User.AccessInstaller
                        onEditDone: {
                                var value = positiveDelayValue(newValue)
                                if (value !== undefined)
                                        item.setValue(value)
                        }
                }
        }
}
