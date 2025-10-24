//// D+ simulator settings page

import QtQuick 1.1
import com.victron.velib 1.0
import QtDBus 1.0
import "PageSettingsDPlusSimulatorUtils.js" as DPlusUtils

MbPage {
        id: root
        title: qsTr("D+ simulator")

        property string settingsPrefix: "com.victronenergy.settings/Settings/Devices/DPlusSim"
        property var relayOptions: []
        property string relayFunctionTag: "dplus-simulator"
        property string relayFunctionNeutral: "none"
        property string mosfetFunctionPath: ""
        property var mosfetRestoreValue: undefined
        property bool mosfetValueReady: false
        property string lastTaggedRelay: ""
        property var relayFunctionRestoreValues: ({})
        property var starterVoltageServices: []
        property string starterVoltageSelection: ""
        property string starterVoltageBus: ""
        property bool starterVoltageScanFailed: false
        property bool starterVoltageHasValue: true
        property bool relayValueReady: false
        property bool outputModeReady: false
        property bool relayInitializationDone: false
        VeQuickItemModel {
                id: relayModel
                source: "com.victronenergy.settings/Settings/Relays"
                onCountChanged: root.refreshRelayOptions()
        }

        function refreshRelayOptions() {
                var options = []
                var validChannels = {}
                for (var i = 0; i < relayModel.count; ++i) {
                        var entry = relayModel.get(i)
                        if (!entry)
                                continue
                        var value = extractRelayValue(entry)
                        if (!value)
                                continue
                        validChannels[value] = true
                        detectMosfetFunctionPath(entry, value)
                        var label = extractRelayLabel(entry, value)
                        options.push({ description: label, value: value })
                }
                relayOptions = options
                for (var channel in root.relayFunctionRestoreValues) {
                        if (!root.relayFunctionRestoreValues.hasOwnProperty(channel))
                                continue
                        if (validChannels[channel])
                                continue
                        delete root.relayFunctionRestoreValues[channel]
                }
                if (root.lastTaggedRelay && !validChannels[root.lastTaggedRelay])
                        root.lastTaggedRelay = ""
        }

        function veItemHasValidValue(item) {
                if (!item)
                        return false
                var hasValue = item.value !== undefined && item.value !== null
                if (item.valid === undefined)
                        return hasValue
                return item.valid && hasValue
        }

        function detectMosfetFunctionPath(entry, value) {
                var candidateValue = value ? value.toString() : ""
                var candidateLower = candidateValue.toLowerCase()
                var derivedPath = candidateValue.length ? relayFunctionPath(candidateValue) : ""
                var discoveredPath = ""

                if (candidateLower.indexOf("mosfet") >= 0 || candidateLower.indexOf("digitaloutput") >= 0)
                        discoveredPath = derivedPath

                if (!discoveredPath && entry && entry.value && entry.value.FunctionPath) {
                        var explicitPath = entry.value.FunctionPath.toString()
                        if (explicitPath.toLowerCase().indexOf("digitaloutput") >= 0)
                                discoveredPath = explicitPath
                }

                if (!discoveredPath || !discoveredPath.length)
                        return

                if (!root.mosfetFunctionPath || !root.mosfetFunctionPath.length)
                        root.mosfetFunctionPath = discoveredPath

                if (root.mosfetFunctionPath !== discoveredPath)
                        return

                var restore = readFunctionValue(root.mosfetFunctionPath)
                var hasRestore = restore !== undefined && restore !== null
                if (hasRestore)
                        root.mosfetRestoreValue = restore
                root.mosfetValueReady = hasRestore
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

        Component.onCompleted: {
                refreshRelayOptions()
                root.relayValueReady = veItemHasValidValue(relaySelector.item)
                root.outputModeReady = veItemHasValidValue(outputModeOptions.item)
                initializeRelayAssignment()
                discoverStarterVoltageServices()
        }

        function destroyObject(obj) {
                if (obj && obj.destroy)
                        obj.destroy()
        }

        function createDbusInterface(busName, service, path, iface) {
                var enumName = busName === "session" ? "SessionBus" : "SystemBus"
                try {
                        return Qt.createQmlObject(
                                'import QtDBus 1.0; DBusInterface { service: "' +
                                        service + '"; path: "' + path +
                                        '"; interface: "' + iface +
                                        '"; bus: DBus.Connection.' + enumName + ' }',
                                root
                        )
                } catch (error) {
                        console.warn("DBusInterface konnte nicht erstellt werden:", error)
                        return null
                }
        }

        function listDbusNames(busName) {
                var iface = createDbusInterface(busName, "org.freedesktop.DBus",
                                                "/org/freedesktop/DBus",
                                                "org.freedesktop.DBus")
                if (!iface)
                        return []
                var reply
                try {
                        reply = iface.call("ListNames")
                } catch (error) {
                        console.warn("org.freedesktop.DBus.ListNames fehlgeschlagen:", error)
                        destroyObject(iface)
                        return []
                }
                destroyObject(iface)
                if (!reply)
                        return []
                if (reply.length === 1 && reply[0] instanceof Array)
                        return reply[0]
                if (reply instanceof Array)
                        return reply
                return []
        }

        function serviceDescription(service, busName, voltage) {
                var description = service
                if (service === "com.victronenergy.system")
                        description = qsTr("Victron Systemdienst (%1)").arg(service)
                else if (service.indexOf("com.victronenergy.battery.") === 0)
                        description = qsTr("Batteriedienst (%1)").arg(service)
                if (voltage !== undefined && voltage !== null && voltage !== "")
                        description += qsTr(" – aktuelle Spannung: %1 V").arg(voltage)
                if (busName === "session")
                        description += qsTr(" [Session]")
                return description
        }

        function readStarterVoltage(busName, service, path) {
                var objectPath = path && path.length ? path : "/StarterVoltage"
                if (objectPath.charAt(0) !== "/")
                        objectPath = "/" + objectPath
                var iface = createDbusInterface(busName, service, objectPath,
                                                "com.victronenergy.BusItem")
                if (!iface)
                        return undefined
                var value
                try {
                        value = iface.call("GetValue")
                } catch (error) {
                        console.warn("StarterVoltage konnte nicht gelesen werden von", service, error)
                        destroyObject(iface)
                        return undefined
                }
                destroyObject(iface)
                if (value === undefined || value === null)
                        return undefined
                if (value.length === 1 && value[0] !== undefined)
                        return value[0]
                return value
        }

        function discoverStarterVoltageServices() {
                var buses = [
                        { name: "system", prefix: "com.victronenergy." },
                        { name: "session", prefix: "com.victronenergy." }
                ]
                var options = []
                starterVoltageScanFailed = false
                for (var i = 0; i < buses.length; ++i) {
                        var bus = buses[i]
                        var names = listDbusNames(bus.name)
                        if (!names.length)
                                continue
                        for (var j = 0; j < names.length; ++j) {
                                var name = names[j]
                                if (typeof name !== "string" || name.indexOf(bus.prefix) !== 0)
                                        continue
                                if (name.indexOf("com.victronenergy.battery.") !== 0 &&
                                                name !== "com.victronenergy.system")
                                        continue
                                var voltage = readStarterVoltage(bus.name, name, "/StarterVoltage")
                                if (voltage === undefined)
                                        continue
                                options.push({
                                        description: serviceDescription(name, bus.name, voltage),
                                        value: name,
                                        voltage: voltage,
                                        bus: bus.name
                                })
                        }
                }
                if (!options.length)
                        starterVoltageScanFailed = true
                else
                        options.sort(function(a, b) { return a.value.localeCompare(b.value) })
                starterVoltageServices = options
                updateStarterVoltageSelectionFromSettings()
        }

        function serviceIsKnown(service) {
                if (!service || !service.length)
                        return false
                for (var i = 0; i < starterVoltageServices.length; ++i) {
                        var option = starterVoltageServices[i]
                        if (option && option.value === service)
                                return true
                }
                return false
        }

        function findStarterVoltageBus(service) {
                if (serviceIsKnown(service)) {
                        for (var i = 0; i < starterVoltageServices.length; ++i) {
                                var option = starterVoltageServices[i]
                                if (option && option.value === service)
                                        return option.bus || "system"
                        }
                }
                return starterVoltageBus || "system"
        }

        function updateStarterVoltageSelectionFromSettings() {
                if (!servicePathItem || !servicePathItem.item || !voltagePathItem || !voltagePathItem.item)
                        return
                var currentService = servicePathItem.item.value
                var currentBus = (dbusBusItem && dbusBusItem.item) ? dbusBusItem.item.value : ""
                starterVoltageSelection = currentService ? currentService.toString() : ""
                starterVoltageBus = currentBus ? currentBus.toString() : ""
                refreshStarterVoltageValidation()
        }

        function onStarterVoltageServiceChanged(service, busName) {
                if (!servicePathItem || !servicePathItem.item || !voltagePathItem || !voltagePathItem.item || !dbusBusItem || !dbusBusItem.item)
                        return
                starterVoltageSelection = service
                starterVoltageBus = busName
                if (servicePathItem.item.setValue)
                        servicePathItem.item.setValue(service)
                if (voltagePathItem.item.setValue)
                        voltagePathItem.item.setValue("/StarterVoltage")
                if (dbusBusItem.item.setValue)
                        dbusBusItem.item.setValue(busName === "session" ? "session" : "system")
                refreshStarterVoltageValidation()
        }

        function starterVoltageServiceValid(service, busName) {
                if (!service || !service.length)
                        return false
                var path = (voltagePathItem && voltagePathItem.item && voltagePathItem.item.value) ?
                        voltagePathItem.item.value.toString() : "/StarterVoltage"
                var voltage = readStarterVoltage(busName || "system", service, path)
                return voltage !== undefined
        }

        function refreshStarterVoltageValidation() {
                starterVoltageHasValue = starterVoltageServiceValid(starterVoltageSelection, starterVoltageBus)
        }

        function initializeRelayAssignment() {
                if (!root.relayValueReady || !root.outputModeReady) {
                        return
                }
                root.relayInitializationDone = true
                var selected = ""
                if (relaySelector.item && relaySelector.item.value)
                        selected = relaySelector.item.value.toString()
                updateRelayFunctionSelection(selected)
        }

        function settingsPath(suffix) {
                return DPlusUtils.path(settingsPrefix, suffix)
        }

        function relayFunctionPath(channel) {
                if (!channel || !channel.toString().length)
                        return ""
                return "com.victronenergy.settings/Settings/Relays/" + channel + "/Function"
        }

        function writeFunctionValue(path, value) {
                if (!path || !path.length)
                        return
                var item = Qt.createQmlObject('import com.victron.velib 1.0; VeQuickItem {}', root)
                item.source = path
                if (item && item.setValue)
                        item.setValue(value)
                if (item)
                        item.destroy()
        }

        function readFunctionValue(path) {
                if (!path || !path.length)
                        return ""
                var item = Qt.createQmlObject('import com.victron.velib 1.0; VeQuickItem {}', root)
                item.source = path
                var value = ""
                if (item && item.value !== undefined && item.value !== null)
                        value = item.value.toString()
                if (item)
                        item.destroy()
                return value
        }

        function cacheRelayFunction(channel) {
                if (!channel || !channel.length)
                        return
                if (root.relayFunctionRestoreValues[channel] !== undefined)
                        return
                var existing = readFunctionValue(relayFunctionPath(channel))
                if (existing === root.relayFunctionTag)
                        existing = root.relayFunctionNeutral
                if (!existing || !existing.length)
                        existing = root.relayFunctionNeutral
                root.relayFunctionRestoreValues[channel] = existing
        }

        function restoreRelayFunction(channel, fallbackToNeutral) {
                if (!channel || !channel.length)
                        return
                var stored = root.relayFunctionRestoreValues[channel]
                if (stored === undefined && fallbackToNeutral)
                        stored = root.relayFunctionNeutral
                if (stored !== undefined) {
                        writeFunctionValue(relayFunctionPath(channel), stored)
                        delete root.relayFunctionRestoreValues[channel]
                }
        }

        function clearRelayFunction(channel) {
                if (!channel || !channel.length)
                        return
                writeFunctionValue(relayFunctionPath(channel), root.relayFunctionNeutral)
                if (root.relayFunctionRestoreValues[channel] !== undefined)
                        delete root.relayFunctionRestoreValues[channel]
        }

        function ensureExclusiveRelayFunction(activeChannel) {
                for (var channel in root.relayFunctionRestoreValues) {
                        if (!root.relayFunctionRestoreValues.hasOwnProperty(channel))
                                continue
                        if (channel === activeChannel)
                                continue
                        restoreRelayFunction(channel, true)
                }
                for (var i = 0; i < relayModel.count; ++i) {
                        var entry = relayModel.get(i)
                        if (!entry)
                                continue
                        var candidate = extractRelayValue(entry)
                        if (!candidate || !candidate.length || candidate === activeChannel)
                                continue
                        var path = relayFunctionPath(candidate)
                        var current = ""
                        if (entry.value && entry.value.Function !== undefined && entry.value.Function !== null)
                                current = entry.value.Function.toString()
                        else
                                current = readFunctionValue(path)
                        if (current === root.relayFunctionTag)
                                restoreRelayFunction(candidate, true)
                }
        }

        function ensureOutputModeValue(mode) {
                if (!outputModeOptions.item || !root.outputModeReady)
                        return
                var current = outputModeOptions.item.value ? outputModeOptions.item.value.toString() : ""
                if (current === mode)
                        return
                outputModeOptions.item.setValue(mode)
        }

        function updateMosfetFunctionTag(active) {
                if (!root.mosfetFunctionPath || !root.mosfetFunctionPath.length)
                        return
                writeFunctionValue(
                            root.mosfetFunctionPath,
                            active ? root.relayFunctionTag : root.relayFunctionNeutral)
        }

        function restoreMosfetFunction(fallbackToNeutral) {
                if (!root.mosfetFunctionPath || !root.mosfetFunctionPath.length)
                        return
                if (!root.mosfetValueReady)
                        return
                var stored = root.mosfetRestoreValue
                if (stored === undefined || stored === null)
                        return

                var restoreValue = stored
                if (fallbackToNeutral && root.relayFunctionNeutral && root.relayFunctionNeutral.length)
                        restoreValue = root.relayFunctionNeutral

                writeFunctionValue(root.mosfetFunctionPath, restoreValue)
        }

        function updateRelayFunctionSelection(channel) {
                var normalized = channel ? channel.toString() : ""
                var previous = root.lastTaggedRelay
                if (normalized && normalized.length) {
                        if (previous && previous.length && previous !== normalized)
                                restoreRelayFunction(previous, true)
                        cacheRelayFunction(normalized)
                        ensureExclusiveRelayFunction(normalized)
                        if (previous && previous.length && previous !== normalized)
                                restoreMosfetFunction(true)
                        updateMosfetFunctionTag(false)
                        ensureOutputModeValue("relay")
                        writeFunctionValue(relayFunctionPath(normalized), root.relayFunctionTag)
                        root.lastTaggedRelay = normalized
                } else {
                        if (previous && previous.length)
                                restoreRelayFunction(previous, true)
                        ensureExclusiveRelayFunction("")
                        restoreMosfetFunction(true)
                        root.lastTaggedRelay = ""
                        if (relaySelector.item && relaySelector.item.value && relaySelector.item.value.length)
                                relaySelector.item.setValue("")
                        ensureOutputModeValue("gpio")
                }
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
                                MbOption { description: qsTr("GPIO-Pin (automatisch aktiv ohne Relay-Zuweisung)"); value: "gpio" },
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
                        possibleValues: relayOptions.length ?
                                ([{ description: qsTr("Kein Relais (GPIO nutzen)"), value: "" }].concat(relayOptions)) : [
                                MbOption { description: qsTr("Keine Relays gefunden"); value: "" }
                        ]
                        show: relayOptions.length > 0
                }

                Connections {
                        target: relaySelector.item
                        onValueChanged: {
                                if (!relaySelector.item)
                                        return
                                root.relayValueReady = veItemHasValidValue(relaySelector.item)
                                if (!root.relayValueReady) {
                                        root.relayInitializationDone = false
                                        return
                                }
                                if (!root.relayInitializationDone) {
                                        if (root.outputModeReady)
                                                initializeRelayAssignment()
                                        return
                                }
                                if (!root.outputModeReady)
                                        return
                                var selected = relaySelector.item.value ? relaySelector.item.value.toString() : ""
                                if (selected.length === 0) {
                                        updateRelayFunctionSelection("")
                                        return
                                }
                                if (outputModeOptions.item && outputModeOptions.item.value !== "relay")
                                        outputModeOptions.item.setValue("relay")
                                updateRelayFunctionSelection(selected)
                        }
                }

                Connections {
                        target: outputModeOptions.item
                        onValueChanged: {
                                if (!outputModeOptions.item)
                                        return
                                root.outputModeReady = veItemHasValidValue(outputModeOptions.item)
                                if (!root.outputModeReady) {
                                        root.relayInitializationDone = false
                                        return
                                }
                                if (!root.relayInitializationDone) {
                                        if (root.relayValueReady)
                                                initializeRelayAssignment()
                                        return
                                }
                                var mode = outputModeOptions.item.value ? outputModeOptions.item.value.toString() : ""
                                if (mode === "gpio")
                                        updateRelayFunctionSelection("")
                                else if (mode === "relay" && relaySelector.item && relaySelector.item.value)
                                        updateRelayFunctionSelection(relaySelector.item.value.toString())
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
                        description: qsTr("Statusintervall [s]")
                        item.bind: settingsPath("/StatusPublishInterval")
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
                        text: starterVoltageScanFailed ?
                                qsTr("Keine Dienste mit /StarterVoltage gefunden. Bitte Starter-Bus-Verkabelung sowie die Konfiguration von System- oder BMV-/SmartShunt-Diensten prüfen. Ohne gültige Quelle bleibt der Simulator gestoppt; kontaktieren Sie den Support, wenn weiterhin keine Starterspannung gemeldet wird.") :
                                qsTr("Wähle den Dienst, der /StarterVoltage bereitstellt. Die Felder darunter werden automatisch gesetzt und sind schreibgeschützt, damit der erkannte Pfad erhalten bleibt.")
                        wrapMode: Text.WordWrap
                }

                MbItemOptions {
                        id: starterVoltageSelector
                        description: qsTr("Starterspannungsdienst")
                        bind: settingsPath("/ServicePath")
                        possibleValues: {
                                var values = []
                                for (var i = 0; i < starterVoltageServices.length; ++i) {
                                        var entry = starterVoltageServices[i]
                                        if (!entry)
                                                continue
                                        values.push({
                                                description: entry.description,
                                                value: entry.value,
                                                bus: entry.bus || "system",
                                                voltage: entry.voltage
                                        })
                                }
                                if (!values.length)
                                        values.push({ description: qsTr("Keine Dienste gefunden"), value: starterVoltageSelection || "" })
                                return values
                        }
                }

                Connections {
                        target: starterVoltageSelector.item
                        onValueChanged: {
                                if (!starterVoltageSelector.item)
                                        return
                                var selected = starterVoltageSelector.item.value ? starterVoltageSelector.item.value.toString() : ""
                                var known = serviceIsKnown(selected)
                                var busName = known ? findStarterVoltageBus(selected) :
                                        (dbusBusItem.item && dbusBusItem.item.value ? dbusBusItem.item.value.toString() : "system")
                                if (known)
                                        onStarterVoltageServiceChanged(selected, busName)
                                else {
                                        starterVoltageSelection = selected
                                        starterVoltageBus = busName
                                        refreshStarterVoltageValidation()
                                }
                        }
                }

                MbItemText {
                        text: qsTr("⚠️ Warnung: Der ausgewählte Dienst liefert keine Starterspannung. Bitte Verkabelung, Messgeräte (z. B. BMV/SmartShunt) und den laufenden Venus-OS-Dienst prüfen.")
                        wrapMode: Text.WordWrap
                        show: starterVoltageSelection.length > 0 && !starterVoltageHasValue
                }

                MbEditBox {
                        id: dbusBusItem
                        description: qsTr("DBus-Bus")
                        item.bind: settingsPath("/DbusBus")
                        maximumLength: 40
                        enabled: false
                }

                MbEditBox {
                        id: servicePathItem
                        description: qsTr("Service-Pfad")
                        item.bind: settingsPath("/ServicePath")
                        maximumLength: 80
                        enabled: false
                }

                MbEditBox {
                        id: voltagePathItem
                        description: qsTr("Spannungspfad")
                        item.bind: settingsPath("/VoltagePath")
                        maximumLength: 80
                        enabled: false
                }

                Connections {
                        target: servicePathItem.item
                        onValueChanged: updateStarterVoltageSelectionFromSettings()
                }

                Connections {
                        target: dbusBusItem.item
                        onValueChanged: updateStarterVoltageSelectionFromSettings()
                }

                Connections {
                        target: voltagePathItem.item
                        onValueChanged: refreshStarterVoltageValidation()
                }
        }
}
