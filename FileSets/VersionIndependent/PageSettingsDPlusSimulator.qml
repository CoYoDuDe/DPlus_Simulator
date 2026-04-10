import QtQuick 2
import "utils.js" as Utils
import com.victron.velib 1.0

MbPage {
	id: root
	title: qsTr("D+ Simulator")

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
		MbItemOptions {
			description: qsTr("Ausgangsmodus")
			bind: root.settingsPath("/OutputMode")
			possibleValues: [
				MbOption { description: qsTr("GPIO-Pin"); value: "gpio" },
				MbOption { description: qsTr("Relay"); value: "relay" }
			]
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
			description: qsTr("Relay-Kanal")
			item.bind: root.settingsPath("/RelayChannel")
			maximumLength: 40
			overwriteMode: false
			show: root.textValue(root.outputModeItem, "gpio") === "relay"
			writeAccessLevel: User.AccessInstaller
		}

		MbSwitch {
			name: qsTr("Zündsignal verwenden")
			bind: root.settingsPath("/UseIgnition")
			valueTrue: 1
			valueFalse: 0
			writeAccessLevel: User.AccessInstaller
		}

		MbEditBox {
			description: qsTr("Zünd-GPIO")
			item.bind: root.settingsPath("/IgnitionGpio")
			maximumLength: 2
			show: root.useIgnitionItem.valid && root.useIgnitionItem.value
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = parseInt(newValue, 10)
				if (!isNaN(value))
					item.setValue(value)
			}
		}

		MbItemOptions {
			description: qsTr("Zünd-Pull-Konfiguration")
			bind: root.settingsPath("/IgnitionPull")
			possibleValues: [
				MbOption { description: qsTr("Floating"); value: "none" },
				MbOption { description: qsTr("Pull-down"); value: "down" },
				MbOption { description: qsTr("Pull-up"); value: "up" }
			]
			show: root.useIgnitionItem.valid && root.useIgnitionItem.value
			writeAccessLevel: User.AccessInstaller
		}

		MbItemOptions {
			description: qsTr("D-Bus")
			bind: root.settingsPath("/DbusBus")
			possibleValues: [
				MbOption { description: qsTr("System"); value: "system" },
				MbOption { description: qsTr("Session"); value: "session" }
			]
			writeAccessLevel: User.AccessInstaller
		}

		MbEditBox {
			description: qsTr("Zielspannung [V]")
			item.bind: root.settingsPath("/TargetVoltage")
			maximumLength: 6
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.numericValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbEditBox {
			description: qsTr("Hysterese [V]")
			item.bind: root.settingsPath("/Hysteresis")
			maximumLength: 5
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.numericValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
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
			description: qsTr("Aktivierungsverzögerung [s]")
			item.bind: root.settingsPath("/ActivationDelaySeconds")
			maximumLength: 6
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.positiveDelayValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbEditBox {
			description: qsTr("Deaktivierungsverzögerung [s]")
			item.bind: root.settingsPath("/DeactivationDelaySeconds")
			maximumLength: 6
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.positiveDelayValue(newValue)
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

		MbEditBox {
			description: qsTr("Statusintervall [s]")
			item.bind: root.settingsPath("/StatusPublishInterval")
			maximumLength: 6
			writeAccessLevel: User.AccessInstaller
			onEditDone: {
				var value = root.positiveDelayValue(newValue)
				if (value !== undefined)
					item.setValue(value)
			}
		}

		MbSwitch {
			name: qsTr("Erzwungen EIN")
			bind: root.settingsPath("/ForceOn")
			valueTrue: 1
			valueFalse: 0
			writeAccessLevel: User.AccessInstaller
		}

		MbSwitch {
			name: qsTr("Erzwungen AUS")
			bind: root.settingsPath("/ForceOff")
			valueTrue: 1
			valueFalse: 0
			writeAccessLevel: User.AccessInstaller
		}

		MbItemText {
			text: qsTr("Erkannter Dienst: %1").arg(root.textValue(root.servicePathStatusItem, qsTr("noch nicht erkannt")))
			wrapMode: Text.WordWrap
		}

		MbItemText {
			text: qsTr("Spannungspfad: %1").arg(root.textValue(root.voltagePathStatusItem, "/StarterVoltage"))
			wrapMode: Text.WordWrap
		}

		MbItemText {
			text: qsTr("Aktiver D-Bus: %1").arg(root.textValue(root.dbusBusStatusItem, "system"))
			wrapMode: Text.WordWrap
		}
	}
}
