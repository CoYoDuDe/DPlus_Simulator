import QtQuick 2
import "utils.js" as Utils
import com.victron.velib 1.0

MbPage {
	id: root
	title: qsTr("D+ Simulator")

	property string settingsPrefix: "com.victronenergy.settings/Settings/Devices/DPlusSim"
	property VBusItem relayTargetItem: VBusItem { bind: settingsPath("/RelayTarget") }
	property VBusItem manualOverrideItem: VBusItem { bind: settingsPath("/ManualOverride") }
	property VBusItem outputModeItem: VBusItem { bind: settingsPath("/OutputMode") }
	property VBusItem sourceModeItem: VBusItem { bind: settingsPath("/VoltageSourceMode") }
	property VBusItem outputStateItem: VBusItem { bind: settingsPath("/OutputState") }
	property VBusItem servicePathItem: VBusItem { bind: settingsPath("/ServicePath") }
	property VBusItem voltagePathItem: VBusItem { bind: settingsPath("/VoltagePath") }
	property string selectedVoltageBind: {
		var service = textValue(servicePathItem, "")
		var path = textValue(voltagePathItem, "")
		if (service.length && path.length)
			return service + path
		return ""
	}
	property VBusItem currentSourceVoltageItem: VBusItem { bind: root.selectedVoltageBind }

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

	function voltageText(item, fallback) {
		if (item && item.valid && item.value !== undefined && item.value !== null) {
			var value = parseFloat(item.value)
			if (!isNaN(value))
				return value.toFixed(2)
		}
		return fallback || "--"
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
		MbSwitch {
			name: qsTr("D+ Simulator aktiv")
			bind: root.settingsPath("/Enabled")
			valueTrue: 1
			valueFalse: 0
			writeAccessLevel: User.AccessInstaller
		}

		MbSwitch {
			name: qsTr("Manuelle Steuerung")
			bind: root.settingsPath("/ManualOverride")
			valueTrue: 1
			valueFalse: 0
			writeAccessLevel: User.AccessInstaller
		}

		MbSwitch {
			name: qsTr("D+ Signal")
			bind: root.settingsPath("/OutputState")
			valueTrue: 1
			valueFalse: 0
			enabled: false
			show: !(root.manualOverrideItem.valid && root.manualOverrideItem.value)
		}

		MbSwitch {
			name: qsTr("D+ Signal")
			bind: root.settingsPath("/ManualState")
			valueTrue: 1
			valueFalse: 0
			show: root.manualOverrideItem.valid && root.manualOverrideItem.value
			writeAccessLevel: User.AccessInstaller
		}

		MbItemOptions {
			description: qsTr("Ausgangsmodus")
			bind: root.settingsPath("/OutputMode")
			possibleValues: [
				MbOption { description: qsTr("GPIO-Pin"); value: "gpio" },
				MbOption { description: qsTr("Relay"); value: "relay" }
			]
			writeAccessLevel: User.AccessInstaller
		}

		MbItemOptions {
			description: qsTr("Relay-Ziel")
			bind: root.settingsPath("/RelayTarget")
			possibleValues: [
				MbOption { description: qsTr("System-Relay"); value: "system" },
				MbOption { description: qsTr("BMV-Relay"); value: "bmv" }
			]
			show: root.textValue(root.outputModeItem, "gpio") === "relay"
			writeAccessLevel: User.AccessInstaller
		}

		MbEditBox {
			description: qsTr("GPIO-Pin")
			item.bind: root.settingsPath("/GpioPin")
			maximumLength: 2
			show: root.textValue(root.outputModeItem, "gpio") !== "relay"
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = parseInt(newValue, 10)
				if (!isNaN(value))
					item.setValue(value)
			}
		}

		MbEditBox {
			description: qsTr("Relay-Kanal (0-5)")
			item.bind: root.settingsPath("/RelayChannel")
			maximumLength: 40
			overwriteMode: false
			show: root.textValue(root.outputModeItem, "gpio") === "relay"
				&& root.textValue(root.relayTargetItem, "system") === "system"
			writeAccessLevel: User.AccessInstaller
		}

		MbItemOptions {
			description: qsTr("Spannungsquelle")
			bind: root.settingsPath("/VoltageSourceMode")
			possibleValues: [
				MbOption { description: qsTr("Automatisch"); value: "auto" },
				MbOption { description: qsTr("Manuell"); value: "manual" }
			]
			writeAccessLevel: User.AccessInstaller
		}

		MbEditBox {
			description: qsTr("D-Bus-Dienst")
			item.bind: root.settingsPath("/ServicePath")
			maximumLength: 64
			show: root.textValue(root.sourceModeItem, "auto") === "manual"
			writeAccessLevel: User.AccessInstaller
		}

		MbEditBox {
			description: qsTr("Spannungspfad")
			item.bind: root.settingsPath("/VoltagePath")
			maximumLength: 64
			show: root.textValue(root.sourceModeItem, "auto") === "manual"
			writeAccessLevel: User.AccessInstaller
		}

		MbEditBox {
			description: qsTr("Einschaltspannung [V]")
			item.bind: root.settingsPath("/OnVoltage")
			maximumLength: 5
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.numericValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbEditBox {
			description: qsTr("Ausschaltspannung [V]")
			item.bind: root.settingsPath("/OffVoltage")
			maximumLength: 5
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.numericValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbEditBox {
			description: qsTr("Einschaltverzögerung [s]")
			item.bind: root.settingsPath("/OnDelaySec")
			maximumLength: 6
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.positiveDelayValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbEditBox {
			description: qsTr("Ausschaltverzögerung [s]")
			item.bind: root.settingsPath("/OffDelaySec")
			maximumLength: 6
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.positiveDelayValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbItemText {
			text: qsTr("Aktuelle Quellenspannung: %1 V").arg(root.voltageText(root.currentSourceVoltageItem, "--"))
			wrapMode: Text.WordWrap
		}
	}
}
