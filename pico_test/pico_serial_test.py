"""
pico_serial_test.py — Autonomer Build/Flash/Test-Loop für RP2040/RP2350-Projekte

Verwendung:
    python pico_serial_test.py --config tests/capcom.json              # nur testen
    python pico_serial_test.py --config tests/capcom.json --flash      # flashen + testen
    python pico_serial_test.py --config tests/capcom.json --build --flash  # alles

Autonomer Loop (iteriert bis alle Tests bestehen oder max_iterations erreicht):
    python pico_serial_test.py --config tests/capcom.json --flash --loop
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import time

import serial
import serial.tools.list_ports


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

OPENOCD_EXE     = r"C:\Users\StundnerMarco\.pico-sdk\openocd\0.12.0+dev\openocd.exe"
OPENOCD_SCRIPTS = r"C:\Users\StundnerMarco\.pico-sdk\openocd\0.12.0+dev\scripts"
AUTO_DETECT_PORTS = ["COM3", "COM4", "COM5"]


# ---------------------------------------------------------------------------
# Phase 1: Build
# ---------------------------------------------------------------------------

def run_build(build_dir: str) -> bool:
    """Führt cmake --build aus. Gibt True bei Erfolg zurück."""
    print(f"\n[BUILD] cmake --build {build_dir}")
    result = subprocess.run(
        ["cmake", "--build", build_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("[BUILD] FEHLER:")
        print(result.stdout[-2000:] if result.stdout else "")
        print(result.stderr[-2000:] if result.stderr else "")
        return False
    print("[BUILD] OK")
    return True


# ---------------------------------------------------------------------------
# Phase 2: Flash via OpenOCD
# ---------------------------------------------------------------------------

def run_flash(elf_path: str, target_cfg: str, boot_delay: float = 2.0) -> bool:
    """Flasht das ELF via OpenOCD (CMSIS-DAP → SWD). Gibt True bei Erfolg zurück."""
    cmd = [
        OPENOCD_EXE,
        "-s", OPENOCD_SCRIPTS,
        "-f", "interface/cmsis-dap.cfg",
        "-f", f"target/{target_cfg}",
        "-c", "adapter speed 5000",
        "-c", f'program "{elf_path}" verify reset exit',
    ]
    print(f"\n[FLASH] {elf_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # OpenOCD schreibt Fortschritt auf stderr
    output = result.stdout + result.stderr
    if result.returncode != 0 or "Error" in output:
        print("[FLASH] FEHLER:")
        print(output[-2000:])
        return False

    print("[FLASH] OK — warte auf Boot ...")
    time.sleep(boot_delay)
    return True


# ---------------------------------------------------------------------------
# Phase 3: COM-Port Erkennung
# ---------------------------------------------------------------------------

def detect_port(candidates: list[str], baud: int, timeout: float = 2.0) -> str | None:
    for port in candidates:
        try:
            s = serial.Serial(port, baud, timeout=timeout)
            s.close()
            print(f"[AUTO]  COM-Port gefunden: {port}")
            return port
        except serial.SerialException:
            pass
    return None


# ---------------------------------------------------------------------------
# Phase 4: Serielles Lesen
# ---------------------------------------------------------------------------

def read_lines(port: str, baud: int, count: int,
               boot_timeout: float, line_timeout: float) -> list[str]:
    lines = []
    with serial.Serial(port, baud, timeout=boot_timeout) as ser:
        print(f"[SERIAL] Warte auf Gerät ({boot_timeout:.0f}s Timeout) ...")
        first = ser.readline().decode("utf-8", errors="replace").strip()
        if not first:
            raise TimeoutError(f"Kein Output innerhalb von {boot_timeout}s auf {port}.")
        lines.append(first)
        print(f"[RECV]  {first}")

        ser.timeout = line_timeout
        while len(lines) < count:
            raw = ser.readline()
            if not raw:
                raise TimeoutError(
                    f"Zeile {len(lines)+1}/{count} nicht innerhalb von "
                    f"{line_timeout}s empfangen."
                )
            line = raw.decode("utf-8", errors="replace").strip()
            lines.append(line)
            print(f"[RECV]  {line}")

    return lines


# ---------------------------------------------------------------------------
# Phase 5: Checks
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, name: str, passed: bool, message: str):
        self.name    = name
        self.passed  = passed
        self.message = message


def check_header(lines: list[str], cfg: dict) -> CheckResult:
    pattern    = cfg["pattern"]
    search_in  = lines[:cfg.get("search_lines", 3)]
    for line in search_in:
        if re.search(pattern, line):
            return CheckResult("header", True, f"Match: '{line}'")
    return CheckResult(
        "header", False,
        f"Pattern '{pattern}' nicht in den ersten {len(search_in)} Zeilen."
    )


def check_float_range(lines: list[str], cfg: dict) -> CheckResult:
    skip     = cfg.get("skip_lines", 1)
    samples  = cfg.get("samples", 10)
    lo, hi   = cfg["min"], cfg["max"]
    pattern  = cfg.get("pattern", r"[-+]?[0-9]*\.?[0-9]+")

    values = []
    for line in lines[skip:]:
        m = re.search(pattern, line)
        if m:
            values.append(float(m.group()))
        if len(values) >= samples:
            break

    if len(values) < samples:
        return CheckResult(
            "float_range", False,
            f"Nur {len(values)}/{samples} verwertbare Werte empfangen."
        )

    out_of_range = [v for v in values if not (lo <= v <= hi)]
    if out_of_range:
        return CheckResult(
            "float_range", False,
            f"{len(out_of_range)}/{samples} Werte außerhalb [{lo}, {hi}]: "
            f"{out_of_range[:5]}{'…' if len(out_of_range) > 5 else ''}"
        )

    mean  = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    return CheckResult(
        "float_range", True,
        f"{samples}/{samples} in [{lo}, {hi}] | mean={mean:.3f}  σ={stdev:.4f}"
    )


CHECK_HANDLERS = {
    "header":      check_header,
    "float_range": check_float_range,
}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: list[CheckResult], iteration: int | None = None) -> bool:
    label = f"  TEST REPORT" + (f"  (Iteration {iteration})" if iteration else "")
    print("\n" + "=" * 60)
    print(label)
    print("=" * 60)
    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name:<16}  {r.message}")
        if not r.passed:
            all_passed = False
    print("=" * 60)
    print(f"  {'ALLE TESTS BESTANDEN' if all_passed else 'FEHLER — Tests nicht bestanden'}")
    print("=" * 60 + "\n")
    return all_passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autonomer Pico Build/Flash/Test-Loop")
    parser.add_argument("--config",         required=True,            help="Pfad zur JSON-Testkonfiguration")
    parser.add_argument("--port",           default=None,             help="COM-Port (auto-detect wenn weggelassen)")
    parser.add_argument("--baud",           type=int, default=None,   help="Baudrate (überschreibt Config)")
    parser.add_argument("--build",          action="store_true",      help="Projekt vor dem Flashen bauen")
    parser.add_argument("--flash",          action="store_true",      help="Firmware vor dem Test flashen")
    parser.add_argument("--loop",           action="store_true",      help="Wiederholen bis Tests bestehen")
    parser.add_argument("--max-iterations", type=int, default=5,      help="Max. Iterationen im Loop-Modus (default: 5)")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    baud         = args.baud or cfg.get("baud", 115200)
    boot_timeout = cfg.get("timeout_boot", 10)
    line_timeout = cfg.get("timeout_line", 3)
    total_lines  = cfg.get("total_lines", 25)
    project      = cfg.get("project", "Unknown")
    build_dir    = cfg.get("build_dir")
    elf_path     = cfg.get("elf_path")
    target_cfg   = cfg.get("target_cfg", "rp2350.cfg")

    print(f"\n{'='*60}")
    print(f"  Projekt : {project}")
    print(f"  Modus   : {'Build + ' if args.build else ''}{'Flash + ' if args.flash else ''}Test"
          + (" (Loop)" if args.loop else ""))
    print(f"{'='*60}")

    max_iter = args.max_iterations if args.loop else 1

    for iteration in range(1, max_iter + 1):
        if args.loop:
            print(f"\n--- Iteration {iteration}/{max_iter} ---")

        # Build
        if args.build:
            if not build_dir:
                print("[ERROR] 'build_dir' fehlt in der Config.", file=sys.stderr)
                sys.exit(1)
            if not run_build(build_dir):
                print("[ABORT] Build fehlgeschlagen.")
                sys.exit(1)

        # Flash
        if args.flash:
            if not elf_path:
                print("[ERROR] 'elf_path' fehlt in der Config.", file=sys.stderr)
                sys.exit(1)
            if not run_flash(elf_path, target_cfg):
                print("[ABORT] Flash fehlgeschlagen.")
                sys.exit(1)

        # COM-Port
        port = args.port or detect_port(AUTO_DETECT_PORTS, baud)
        if port is None:
            print(f"[ERROR] Kein Gerät auf {AUTO_DETECT_PORTS}.", file=sys.stderr)
            sys.exit(1)
        print(f"[INFO]  Port={port}  Baud={baud}")

        # Lesen
        try:
            lines = read_lines(port, baud, total_lines, boot_timeout, line_timeout)
        except TimeoutError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            if not args.loop:
                sys.exit(1)
            continue

        # Checks
        results = []
        for check_cfg in cfg.get("checks", []):
            handler = CHECK_HANDLERS.get(check_cfg.get("type"))
            if handler:
                results.append(handler(lines, check_cfg))

        passed = print_report(results, iteration if args.loop else None)

        if passed:
            sys.exit(0)

        if iteration < max_iter:
            print("[LOOP] Teste erneut nach nächstem Flash ...")

    print("[LOOP] Maximale Iterationen erreicht — Tests nicht bestanden.")
    sys.exit(1)


if __name__ == "__main__":
    main()
