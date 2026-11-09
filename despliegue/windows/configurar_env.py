"""
Crea o ajusta el .env de producción a partir de .env.example.

    python despliegue\\windows\\configurar_env.py --crear --db-password CLAVE
    python despliegue\\windows\\configurar_env.py --dominio tiocampo.ejemplo.ts.net
    python despliegue\\windows\\configurar_env.py --red-local 192.168.1.50

Al crear genera DJANGO_SECRET_KEY y las claves de cifrado. NUNCA reemplaza un
.env que ya existe con --crear (perder las claves de cifrado = perder los datos).
"""

import argparse
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

RAIZ = Path(__file__).resolve().parents[2]
ENV = RAIZ / ".env"
PLANTILLA = RAIZ / ".env.example"


def leer(ruta):
    return ruta.read_text(encoding="utf-8").splitlines()


def fijar(lineas, valores):
    """Reemplaza KEY=... conservando comentarios y orden; agrega las que falten al final."""
    pendientes = dict(valores)
    salida = []
    for linea in lineas:
        clave = linea.split("=", 1)[0].strip()
        if not linea.lstrip().startswith("#") and "=" in linea and clave in pendientes:
            salida.append(f"{clave}={pendientes.pop(clave)}")
        else:
            salida.append(linea)
    if pendientes:
        salida.append("")
        salida.extend(f"{clave}={valor}" for clave, valor in pendientes.items())
    return salida


def valores_dominio(dominio):
    dominio = dominio.strip().removeprefix("https://").removeprefix("http://").strip("/")
    return {
        "ALLOWED_HOSTS": f"{dominio},127.0.0.1,localhost",
        "PUBLIC_BASE_URL": f"https://{dominio}",
        "CSRF_TRUSTED_ORIGINS": f"https://{dominio}",
        # Internet: Waitress solo local, Tailscale entrega HTTPS.
        "SERVIDOR_ESCUCHA": "127.0.0.1:8000",
        "SERVIDOR_ESQUEMA": "https",
        "COOKIES_SEGURAS": "1",
        "SECURE_SSL_REDIRECT": "1",
        "SECURE_HSTS_SECONDS": "3600",
    }


def valores_red_local(ip, puerto=8000):
    """Solo para la red de la oficina: http por la IP del servidor, sin internet."""
    ip = ip.strip().removeprefix("http://").removeprefix("https://").split(":")[0].strip("/")
    origenes = [f"http://{ip}:{puerto}", f"http://tiocampo:{puerto}"]
    return {
        "ALLOWED_HOSTS": f"{ip},tiocampo,127.0.0.1,localhost",
        "PUBLIC_BASE_URL": origenes[0],
        "CSRF_TRUSTED_ORIGINS": ",".join(origenes),
        "SERVIDOR_ESCUCHA": f"0.0.0.0:{puerto}",
        "SERVIDOR_ESQUEMA": "http",
        "COOKIES_SEGURAS": "0",
        "SECURE_SSL_REDIRECT": "0",
        "SECURE_HSTS_SECONDS": "0",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crear", action="store_true", help="Crea el .env de producción.")
    parser.add_argument("--db-password", default="", help="Clave del usuario tiocampo de MySQL.")
    parser.add_argument("--dominio", default="", help="Nombre público, p. ej. tiocampo.xxxx.ts.net")
    parser.add_argument("--red-local", default="", help="IP del servidor en la red de la oficina, p. ej. 192.168.1.50")
    args = parser.parse_args()

    if args.crear:
        if ENV.exists():
            print("Ya existe un .env: no se reemplaza (contiene las claves de cifrado).")
        else:
            valores = {
                "DEBUG": "0",
                "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
                "ALLOWED_HOSTS": "127.0.0.1,localhost",
                "PUBLIC_BASE_URL": "http://127.0.0.1:8000",
                "CSRF_TRUSTED_ORIGINS": "",
                "DB_ENGINE": "django.db.backends.mysql",
                "DB_NAME": "tio_campo",
                "DB_USER": "tiocampo",
                "DB_PASSWORD": args.db_password,
                "DB_HOST": "localhost",
                "DB_PORT": "3306",
                "DATOS_CIFRADO_CLAVES": Fernet.generate_key().decode(),
                "DATOS_HUELLA_CLAVE": secrets.token_urlsafe(48),
                "SERVIR_MEDIA": "1",
                "SECURE_HSTS_SECONDS": "3600",
            }
            ENV.write_text("\n".join(fijar(leer(PLANTILLA), valores)) + "\n", encoding="utf-8")
            print("Se creó el .env de producción con claves nuevas.")

    if args.dominio:
        if not ENV.exists():
            sys.exit("No existe el .env. Ejecute primero instalar.ps1.")
        ENV.write_text("\n".join(fijar(leer(ENV), valores_dominio(args.dominio))) + "\n", encoding="utf-8")
        print(f"Dominio configurado: https://{valores_dominio(args.dominio)['CSRF_TRUSTED_ORIGINS'][8:]}")

    if args.red_local:
        if not ENV.exists():
            sys.exit("No existe el .env. Ejecute primero instalar.ps1.")
        valores = valores_red_local(args.red_local)
        ENV.write_text("\n".join(fijar(leer(ENV), valores)) + "\n", encoding="utf-8")
        print(f"Modo red local: {valores['PUBLIC_BASE_URL']}")


if __name__ == "__main__":
    main()
