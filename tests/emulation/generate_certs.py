"""Generates self-signed CA, server, and client certificates for gRPC mTLS testing.

Runs openssl subprocess commands to produce ca.crt/key, server.crt/key, and
client.crt/key in the specified output directory.
"""

import logging
import os
import subprocess
from typing import List

# Global configurations
DEFAULT_CERT_DIR: str = "Auth/certs"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def generate_certificates(output_dir: str) -> None:
    """Generates CA, server, and client certificates using openssl.

    Args:
        output_dir: Directory where the certificate files should be saved.

    Raises:
        subprocess.SubprocessError: If any openssl command execution fails.
    """
    os.makedirs(output_dir, exist_ok=True)

    # File paths
    ca_key: str = os.path.join(output_dir, "ca.key")
    ca_crt: str = os.path.join(output_dir, "ca.crt")
    server_key: str = os.path.join(output_dir, "server.key")
    server_csr: str = os.path.join(output_dir, "server.csr")
    server_crt: str = os.path.join(output_dir, "server.crt")
    client_key: str = os.path.join(output_dir, "client.key")
    client_csr: str = os.path.join(output_dir, "client.csr")
    client_crt: str = os.path.join(output_dir, "client.crt")
    ext_file: str = os.path.join(output_dir, "server.ext")

    # Write extension configuration to allow localhost and IP bindings
    with open(ext_file, "w", encoding="utf-8") as f:
        f.write(
            "authorityKeyIdentifier=keyid,issuer\n"
            "basicConstraints=CA:FALSE\n"
            "keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment\n"
            "subjectAltName = @alt_names\n\n"
            "[alt_names]\n"
            "DNS.1 = localhost\n"
            "DNS.2 = rainforestpi\n"
            "DNS.3 = nvjetson\n"
            "IP.1 = 127.0.0.1\n"
            "IP.2 = 192.168.8.68\n"
            "IP.3 = 192.168.8.70\n"
        )

    logging.info("Generating CA private key and self-signed root certificate...")
    # Generate CA key
    subprocess.run(
        ["openssl", "genrsa", "-out", ca_key, "2048"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Generate CA cert
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-nodes",
            "-key",
            ca_key,
            "-sha256",
            "-days",
            "365",
            "-out",
            ca_crt,
            "-subj",
            "/CN=MicrogridLocalCA",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    logging.info("Generating Server key and certificate request...")
    # Server private key
    subprocess.run(
        ["openssl", "genrsa", "-out", server_key, "2048"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Server CSR
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            server_key,
            "-out",
            server_csr,
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Sign Server Cert with CA
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            server_csr,
            "-CA",
            ca_crt,
            "-CAkey",
            ca_key,
            "-CAcreateserial",
            "-out",
            server_crt,
            "-days",
            "365",
            "-sha256",
            "-extfile",
            ext_file,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    logging.info("Generating Client key and certificate request...")
    # Client private key
    subprocess.run(
        ["openssl", "genrsa", "-out", client_key, "2048"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Client CSR
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            client_key,
            "-out",
            client_csr,
            "-subj",
            "/CN=MicrogridKioskClient",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Sign Client Cert with CA
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            client_csr,
            "-CA",
            ca_crt,
            "-CAkey",
            ca_key,
            "-CAcreateserial",
            "-out",
            client_crt,
            "-days",
            "365",
            "-sha256",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Clean up CSR files and cert serials to keep folder neat
    for temp_file in [
        server_csr,
        client_csr,
        ext_file,
        os.path.join(output_dir, "ca.srl"),
    ]:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    logging.info(f"mTLS certificates successfully generated under: {output_dir}")


if __name__ == "__main__":
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    workspace_certs: str = os.path.join(script_dir, "..", "..", DEFAULT_CERT_DIR)
    generate_certificates(workspace_certs)
