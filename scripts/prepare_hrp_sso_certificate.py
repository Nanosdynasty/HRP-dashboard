"""Create an HRP Entra application certificate on the host that will use it.

Only send the .cert.pem file to IT. Never copy or transmit the .private.pem file.
"""
import argparse
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix", type=Path, help="Absolute output path prefix outside the repository")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    if not args.prefix.is_absolute() or not 30 <= args.days <= 730:
        parser.error("Use an absolute path and a lifetime of 30–730 days.")
    key_path = Path(str(args.prefix) + ".private.pem")
    cert_path = Path(str(args.prefix) + ".cert.pem")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists() or cert_path.exists():
        parser.error("Output already exists; choose a new prefix for rotation.")
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Howe Robinson Dashboard")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=args.days))
            .sign(key, hashes.SHA256()))
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    # Exclusive creation prevents overwriting a previously deployed credential.
    with os.fdopen(os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400), "wb") as stream:
        stream.write(private)
    with os.fdopen(os.open(cert_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644), "wb") as stream:
        stream.write(cert.public_bytes(serialization.Encoding.PEM))
    if os.name != "nt":
        os.chmod(key_path, 0o400)
        os.chmod(cert_path, 0o644)
    print(f"Public certificate: {cert_path}")
    print(f"SHA-256 thumbprint: {hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest().upper()}")
    print(f"Expires (UTC): {cert.not_valid_after_utc.isoformat()}")
    print("Keep the private key on this host; send only the public certificate to HRP IT.")


if __name__ == "__main__":
    main()
