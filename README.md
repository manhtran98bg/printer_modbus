# printer_modbus

Python console service for printer Modbus integration.

Version: `1.0`

Run from the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.main
```

On Ubuntu:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m src.main
```

Run commands from the project root so Python can resolve the `src` package.

Runtime config is stored at:

```text
Windows: C:\Users\{User_name}\.printer_modbus\storage\config.json
Ubuntu:  /home/{user}/.printer_modbus/storage/config.json
```

SQLite runtime database is stored at:

```text
Windows: C:\Users\{User_name}\.printer_modbus\printer_modbus.db
Ubuntu:  /home/{user}/.printer_modbus/printer_modbus.db
```

## Monitoring dashboard

The application includes a read-only web dashboard for PLC-App-MES status,
batch progress, register values, events, and errors. By default it listens on
all LAN interfaces at:

```text
http://{server-ip}:8080
```

Dashboard settings are stored in the runtime `config.json`:

```json
{
  "dashboard": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8080,
    "refresh_ms": 1000,
    "retention_days": 7
  }
}
```

The dashboard exposes only `GET /` and `GET /api/dashboard`. Communication
events are stored in SQLite and automatically removed after the configured
retention period. Dashboard startup failures are logged without stopping the
printer workflow.

## PLC register protocol

The service polls holding registers D0-D15. PLC requests and server responses are paired:

| Request | Operation | Response |
| --- | --- | --- |
| D0 | Start batch with configured `box_count` (`0` or D6) | D10 |
| D1 | Print next | D11 |
| D2 | Label printed successfully | D12 |
| D3 | Reprint | D13 |
| D4 | End batch | D14 |
| D5 | Reset print flow | D15 |

After a successful start batch response, the service writes
`metaData.autobox_count` from MES to D18 before writing the success response to D10.
Missing or invalid `autobox_count` is treated as a technical error (`D10 = 3`).

For backward compatibility with PLC programs that do not populate D6 yet,
`server.use_d6_box_count` defaults to `false`. In that mode, start batch sends
`{"box_count": 0}`. Set it to `true` to send the value read from D6.

Response values are `0` while pending, `1` for success, `2` for an HTTP 4xx rejection,
and `3` for an HTTP 5xx, timeout, or network failure. The service writes the response
before resetting the request register. The PLC must clear the response register before
starting a new request.
