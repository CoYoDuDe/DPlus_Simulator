//// D+ simulator settings page

import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbPage {
        id: root
        title: qsTr("D+ simulator")

        property string settingsPrefix: "com.victronenergy.settings/Settings/Devices/DPlusSim"
        property var relayOptions: []
        VeQuickItemModel {
                id: relayModel
                source: "com.victronenergy.settings/Settings/Relays"
                onCountChanged: root.refreshRelayOptions()
        }

        function refreshRelayOptions() {
                var options = []
                for (var i = 0; i < relayModel.count; ++i) {
                        var entry = relayModel.get(i)
                        if (!entry)
                                continue
                        var value = extractRelayValue(entry)
                        if (!value)
                                continue
                        var label = extractRelayLabel(entry, value)
                        options.push({ description: label, value: value })
                }
                relayOptions = options
        }

        function extractRelayLabel(entry, fallback) {
                if (entry.displayName)
                        return entry.displayName
                if (entry.value && entry.value.Name)
                        return entry.value.Name
                if (entry.value && entry.value.name)
                        return entry.value.name
                if (entry.name)
                        return entry.name
                return fallback
        }

        function extractRelayValue(entry) {
                var key = ""
                if (entry.uniqueKey)
                        key = entry.uniqueKey.toString()
                else if (entry.path)
                        key = entry.path.toString()
                if (!key && entry.value && entry.value.Path)
                        key = entry.value.Path.toString()
                if (!key && entry.value && entry.value.StatePath)
                        key = entry.value.StatePath.toString()
                if (!key)
                        return ""
                var relaysPrefix = "/Settings/Relays/"
                var index = key.indexOf(relaysPrefix)
                if (index >= 0)
                        key = key.slice(index + relaysPrefix.length)
                key = key.replace(/^Relays\//, "")
                key = key.replace(/^\//, "")
                key = key.replace(/\/State$/i, "")
                return key
        }

        Component.onCompleted: refreshRelayOptions()

        function settingsPath(suffix) {
                return Utils.path(settingsPrefix, suffix)
        }

        model: VisibleItemModel {
                MbItemText {
                        text: qsTr("Konfiguriere den virtuellen D+-Ausgang des D+ Simulator-Dienstes.")
                        wrapMode: Text.WordWrap
                }

                MbItemText {
                        text: qsTr("Eingänge")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbItemOptions {
                        id: outputModeOptions
                        description: qsTr("Ausgangsmodus")
                        bind: settingsPath("/OutputMode")
                        possibleValues: [
                                MbOption { description: qsTr("GPIO-Pin"); value: "gpio" },
                                MbOption { description: qsTr("Relay"); value: "relay" }
                        ]
                }

                MbEditBox {
                        description: qsTr("GPIO-Pin")
                        item.bind: settingsPath("/GpioPin")
                        inputMethodHints: Qt.ImhDigitsOnly
                        maximumLength: 2
                        show: outputModeOptions.item.value !== "relay"
                        onEditDone: {
                                var v = parseInt(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
                        }
                }

                MbItemOptions {
                        id: relaySelector
                        description: qsTr("Relay-Kanal")
                        bind: settingsPath("/RelayChannel")
                        possibleValues: relayOptions.length ? relayOptions : [
                                MbOption { description: qsTr("Keine Relays gefunden"); value: "" }
                        ]
                        show: relayOptions.length > 0
                }

                Connections {
                        target: relaySelector.item
                        onValueChanged: {
                                if (!relaySelector.item)
                                        return
                                var selected = relaySelector.item.value ? relaySelector.item.value.toString() : ""
                                if (selected.length === 0)
                                        return
                                if (outputModeOptions.item && outputModeOptions.item.value !== "relay")
                                        outputModeOptions.item.setValue("relay")
                        }
                }

                MbSwitch {
                        id: useIgnitionSwitch
                        name: qsTr("Zündsignal verwenden")
                        bind: settingsPath("/UseIgnition")
                        valueTrue: 1
                        valueFalse: 0
                }

                MbEditBox {
                        description: qsTr("Zünd-GPIO")
                        item.bind: settingsPath("/IgnitionGpio")
                        inputMethodHints: Qt.ImhDigitsOnly
                        maximumLength: 2
                        show: useIgnitionSwitch.item.value
                        onEditDone: {
                                var v = parseInt(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
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
                        show: useIgnitionSwitch.item.value
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
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("Hysterese [V]")
                        item.bind: settingsPath("/Hysteresis")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 5
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("Einschaltspannung [V]")
                        item.bind: settingsPath("/OnVoltage")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 5
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("Ausschaltspannung [V]")
                        item.bind: settingsPath("/OffVoltage")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 5
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
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
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        if (v < 0.2)
                                                v = 0.2
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("Deaktivierungsverzögerung [s]")
                        item.bind: settingsPath("/DeactivationDelaySeconds")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        if (v < 0.2)
                                                v = 0.2
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("Einschaltverzögerung [s]")
                        item.bind: settingsPath("/OnDelaySec")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        if (v < 0.2)
                                                v = 0.2
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("Ausschaltverzögerung [s]")
                        item.bind: settingsPath("/OffDelaySec")
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        maximumLength: 6
                        onEditDone: {
                                var v = parseFloat(newValue)
                                if (!isNaN(v)) {
                                        if (v < 0.2)
                                                v = 0.2
                                        item.setValue(v)
                                }
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
                }

                MbSwitch {
                        name: qsTr("Erzwungen AUS")
                        bind: settingsPath("/ForceOff")
                        valueTrue: 1
                        valueFalse: 0
                }

                MbItemText {
                        text: qsTr("Dienstintegration")
                        font.pixelSize: 20
                        font.bold: true
                }

                MbEditBox {
                        description: qsTr("Statusintervall [ms]")
                        item.bind: settingsPath("/StatusPublishInterval")
                        inputMethodHints: Qt.ImhDigitsOnly
                        maximumLength: 5
                        onEditDone: {
                                var v = parseInt(newValue)
                                if (!isNaN(v)) {
                                        item.setValue(v)
                                }
                        }
                }

                MbEditBox {
                        description: qsTr("DBus-Bus")
                        item.bind: settingsPath("/DbusBus")
                        maximumLength: 40
                }

                MbEditBox {
                        description: qsTr("Service-Pfad")
                        item.bind: settingsPath("/ServicePath")
                        maximumLength: 80
                }

                MbEditBox {
                        description: qsTr("Spannungspfad")
                        item.bind: settingsPath("/VoltagePath")
                        maximumLength: 80
                }
        }
}
