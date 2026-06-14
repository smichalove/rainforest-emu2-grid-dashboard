# mTLS Certificates Directory

For production setups, you must generate and place your mutual TLS (mTLS) certificates and keys in the `Auth/certs/` directory (which is ignored by Git to prevent leakage).

For production:
- **Raspberry Pi client**: Needs `ca.crt`, `client.crt`, and `client.key`.
- **Jetson Orin server**: Needs `ca.crt`, `server.crt`, `server.key`, `client.crt`, and `client.key` (for verification).

You can generate these files automatically using the script:
```bash
python3 tests/emulation/generate_certs.py
```
This script will output them directly into the production `Auth/certs/` folder.
