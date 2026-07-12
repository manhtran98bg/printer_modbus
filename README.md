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
