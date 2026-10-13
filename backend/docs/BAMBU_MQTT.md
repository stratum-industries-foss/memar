# Bambu Lab + generic MQTT — setup & hardware verification

MEMAR talks to Bambu Lab printers over their **local (LAN) MQTT** interface, and to
generic devices over MQTT, via a push→poll bridge (`app/mqtt_client.py`). The bridge
runs a background subscribe loop, caches the latest report, and serves it to the
fleet on demand.

> **Status: code-complete, tested against a mocked broker, NOT yet confirmed on real
> hardware.** The Bambu API is unofficial/reverse-engineered. The connection
> parameters and payload schema below are assumptions that can change across Bambu
> firmware. Verify on your printer before trusting the numbers.

## 1. Prerequisites

- `aiomqtt` installed in the deploy venv (it is optional and **not** installed by
  default): `pip install aiomqtt`. Without it the device shows offline with a clear
  "needs the optional aiomqtt package" message — it never crashes the fleet.
- The printer in **LAN Mode** (Bambu Studio / Bambu Handy → Settings → enable LAN
  Mode). Note the **access code** and the printer **serial number**.
- The printer reachable on the LAN (MQTT over TLS on port **8883**).

## 2. Configure the device in MEMAR

Bambu needs two **credential** fields — `serial` and `api_key` — that the add-printer
form and the printer-settings UI do **not** expose (the same is true for every
credentialed protocol, e.g. OctoPrint/Prusa Connect/Duet). Set them by editing the
farm config file directly: `config/devices.yaml` (or `$MEMAR_CONFIG_PATH`), then
restart the backend (or it reloads on the next config write).

```yaml
printers:
  - id: bambu-x1c-1
    name: Bambu X1C (shop)
    protocol: bambu_mqtt
    base_url: 192.168.1.50      # printer LAN IP — MUST be private/loopback/.local
    serial: "01P00A0000000000"  # printer serial (also the MQTT topic id)
    api_key: "12345678"          # LAN access code (Bambu Studio/Handy → LAN Mode)
    machine_type: fdm
    enabled: true
```

| Field      | Value                                                        |
|------------|--------------------------------------------------------------|
| `protocol` | `bambu_mqtt`                                                 |
| `base_url` | the printer's **LAN IP** (e.g. `192.168.1.50`) — must be a private/loopback/.local address |
| `serial`   | printer serial number (also the MQTT topic id)              |
| `api_key`  | LAN access code                                             |

The LAN username is assumed fixed (`bblp`). TLS verification is disabled for the LAN
connection (Bambu uses a self-signed cert), so the adapter **refuses a non-local
host** to avoid leaking the access code.

> UI-based credential entry (add/settings forms accepting `serial` + `api_key`) is a
> follow-up — today these are file-only, like all other credentialed protocols.

## 3. Verify the raw MQTT feed (independent of MEMAR)

Before blaming MEMAR, confirm the printer actually publishes what we assume:

```bash
# Subscribe to the printer's report topic (TLS, no cert check for the self-signed LAN cert)
mosquitto_sub -h <LAN_IP> -p 8883 \
  -u bblp -P <ACCESS_CODE> \
  --insecure --cafile /dev/null \
  -t "device/<SERIAL>/report" -v

# If nothing arrives, trigger a full report (this is what MEMAR's _on_connected does):
mosquitto_pub -h <LAN_IP> -p 8883 -u bblp -P <ACCESS_CODE> --insecure \
  -t "device/<SERIAL>/request" \
  -m '{"pushing":{"sequence_id":"0","command":"pushall"}}'
```

Confirm the JSON has a `print` object with `gcode_state`, `mc_percent`,
`nozzle_temper`, `bed_temper`, `mc_remaining_time`, `layer_num`, `total_layer_num`.
**If the field names or units differ, update `_normalize_bambu` accordingly** — the
mapping assumes `mc_remaining_time` is in minutes and `mc_percent` is 0–100.

## 4. Verify through MEMAR

1. Restart the backend with `aiomqtt` installed.
2. Watch the device on the fleet dashboard. Expected sequence:
   - briefly **offline "Waiting for first MQTT report…"**,
   - then **online** with live state/progress/temps once the first report (or the
     `pushall` response) arrives.
3. If it connects but stays "Waiting…" then goes stale after 120s, the `pushall`
   body/topic is wrong for your firmware — enable debug logging and check the
   `Bambu pushall sent` log line in `_on_connected`.

## Generic MQTT (`protocol: mqtt`)

A **scaffold only**. It subscribes to `machines/{id}/status` and maps a fixed schema
(`state`/`progress`/`nozzle_temp`/`bed_temp`/`filename`). There is no configurable
topic or field mapping yet, so a device publishing anything else will show online
with null fields. Treat it as a starting point, not a turnkey integration.
