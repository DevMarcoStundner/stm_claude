# stm_claude — Claude Code Scripts für Embedded-Projekte

Sammlung von Skripten und Werkzeugen die in Zusammenarbeit mit Claude Code entstanden sind. Aktueller Fokus: autonomes Testen von Raspberry Pi Pico (RP2040/RP2350) Projekten.

---

## Inhalt

| Verzeichnis | Beschreibung |
|---|---|
| `pico_test/` | Autonomer Build/Flash/Test-Runner für RP2040/RP2350 |

---

## pico_test — Autonomer Build/Flash/Test-Runner

Allgemeines Werkzeug zum automatisierten Testen von Raspberry Pi Pico Projekten über die serielle Schnittstelle. Unterstützt die vollständige Pipeline von Build über Flash bis zur Validierung der seriellen Ausgabe.

### Voraussetzungen

| Komponente | Version |
|---|---|
| Python | ≥ 3.10 |
| pyserial | `pip install pyserial` |
| OpenOCD (Pico SDK) | `~/.pico-sdk/openocd/0.12.0+dev/` |
| Debug-Probe | CMSIS-DAP (z.B. Raspberry Pi Debug Probe) |

### Pipeline

```
[1] Build         cmake --build <build_dir>
      ↓
[2] Flash         OpenOCD via CMSIS-DAP → SWD → Target
      ↓
[3] Serial        COM-Port öffnen, Zeilen lesen (auto-detect COM3–COM5)
      ↓
[4] Validate      Checks aus JSON-Config ausführen
      ↓
[5] Report        PASS / FAIL mit Statistik
```

Jede Phase ist optional — es kann auch nur getestet werden wenn das Gerät bereits läuft.

### Verwendung

```bash
# Nur testen (Gerät läuft bereits)
python pico_test/pico_serial_test.py --config pico_test/tests/capcom.json

# Flashen und testen
python pico_test/pico_serial_test.py --config pico_test/tests/capcom.json --flash

# Bauen, flashen und testen
python pico_test/pico_serial_test.py --config pico_test/tests/capcom.json --build --flash

# Autonomer Loop: bis zu 5× iterieren bis alle Tests grün sind
python pico_test/pico_serial_test.py --config pico_test/tests/capcom.json --build --flash --loop --max-iterations 5

# COM-Port manuell angeben (sonst auto-detect COM3–COM5)
python pico_test/pico_serial_test.py --config pico_test/tests/capcom.json --flash --port COM4
```

### Projektkonfiguration (JSON)

Für jedes Projekt wird eine eigene JSON-Datei unter `pico_test/tests/` angelegt:

```json
{
    "project":      "MEIN_PROJEKT",
    "baud":         115200,
    "timeout_boot": 10,
    "timeout_line": 3,
    "total_lines":  22,

    "build_dir":   "C:/Pfad/zum/Projekt/build",
    "elf_path":    "C:/Pfad/zum/Projekt/build/MEIN_PROJEKT.elf",
    "target_cfg":  "rp2350.cfg",

    "checks": [
        {
            "type":         "header",
            "pattern":      "Erwarteter Starttext",
            "search_lines": 3
        },
        {
            "type":       "float_range",
            "skip_lines": 1,
            "samples":    20,
            "min":        490.0,
            "max":        510.0
        }
    ]
}
```

### Check-Typen

| Typ | Beschreibung |
|---|---|
| `header` | Prüft ob eine der ersten N Zeilen einem Regex-Pattern entspricht |
| `float_range` | Parst Fließkommazahlen, prüft Min/Max, gibt Mittelwert und σ aus |

### Beispiel-Output

```
============================================================
  Projekt : CAPCOM
  Modus   : Build + Flash + Test
============================================================
[BUILD] cmake --build .../CAPCOM/build
[BUILD] OK
[FLASH] .../CAPCOM/build/CAPCOM.elf
[FLASH] OK — warte auf Boot ...
[AUTO]  COM-Port gefunden: COM4
[INFO]  Port=COM4  Baud=115200
[SERIAL] Warte auf Gerät (10s Timeout) ...
[RECV]  PIO Pulse Capture Demo (Interrupt-Mode)
[RECV]  499.97
...

============================================================
  TEST REPORT
============================================================
  [PASS] header            Match: 'PIO Pulse Capture Demo (Interrupt-Mode)'
  [PASS] float_range       20/20 in [490.0, 510.0] | mean=499.971  σ=0.0120
============================================================
  ALLE TESTS BESTANDEN
============================================================
```

### Vorhandene Projektkonfigurationen

| Datei | Projekt | Beschreibung |
|---|---|---|
| `pico_test/tests/capcom.json` | CAPCOM | PIO Pulse Capture auf RP2350, prüft 20 Messwerte im Bereich 490–510 µs |

### Neues Projekt hinzufügen

1. `pico_test/tests/<projektname>.json` anlegen
2. `build_dir`, `elf_path` und `target_cfg` anpassen
3. Passende `checks` definieren
4. Testen: `python pico_test/pico_serial_test.py --config pico_test/tests/<projektname>.json`
