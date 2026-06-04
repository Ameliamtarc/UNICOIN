#!/usr/bin/env python3
"""
Ejecuta las comprobaciones locales de calidad y SAST del proyecto.

Bandit se ejecuta como SAST local sobre app.py y src. El analisis de SonarQube
se lanza cuando `sonar-scanner` esta instalado.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SONAR_CONFIG = ROOT / "sonar-project.properties"
REQUIRED_SONAR_KEYS = {
    "sonar.projectKey",
    "sonar.projectName",
    "sonar.sources",
    "sonar.tests",
    "sonar.python.version",
    "sonar.sourceEncoding",
}


def run(command: list[str]) -> int:
    print(f"$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


def load_sonar_properties() -> dict[str, str]:
    if not SONAR_CONFIG.exists():
        raise FileNotFoundError("No existe sonar-project.properties.")

    properties: dict[str, str] = {}
    for raw_line in SONAR_CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def check_sonar_config() -> None:
    properties = load_sonar_properties()
    missing = sorted(REQUIRED_SONAR_KEYS - properties.keys())
    if missing:
        raise ValueError(f"Faltan claves obligatorias de SonarQube: {', '.join(missing)}")

    for key in ("sonar.sources", "sonar.tests"):
        for relative_path in properties[key].split(","):
            path = ROOT / relative_path.strip()
            if not path.exists():
                raise FileNotFoundError(f"La ruta configurada en {key} no existe: {relative_path}")

    print("OK sonar-project.properties valido.", flush=True)


def run_unittests() -> int:
    return run([sys.executable, "-m", "unittest", "-v", "tests.test_iteracion"])


def run_bandit() -> int:
    return run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "app.py",
            "src",
            "-x",
            "tests,uploads,__pycache__",
        ]
    )


def run_sonar(require_sonar: bool) -> int:
    scanner = shutil.which("sonar-scanner")
    if scanner is None:
        message = "sonar-scanner no esta instalado; se omite el analisis SonarQube."
        if require_sonar:
            print(f"ERROR {message}", flush=True)
            return 2
        print(f"WARN {message}", flush=True)
        print(
            "Instalalo desde SonarSource o ejecuta el scanner desde Docker y vuelve a lanzar este script.",
            flush=True,
        )
        return 0

    return run([scanner])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-sonar",
        action="store_true",
        help="Falla si sonar-scanner no esta instalado localmente.",
    )
    parser.add_argument(
        "--skip-bandit",
        action="store_true",
        help="Omite el analisis SAST local con Bandit.",
    )
    args = parser.parse_args()

    try:
        check_sonar_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 2

    tests_status = run_unittests()
    if tests_status != 0:
        return tests_status

    if not args.skip_bandit:
        bandit_status = run_bandit()
        if bandit_status != 0:
            return bandit_status

    return run_sonar(args.require_sonar)


if __name__ == "__main__":
    raise SystemExit(main())
