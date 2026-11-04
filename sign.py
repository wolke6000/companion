import argparse
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser(description="Sign an existing Companion build.")
    parser.add_argument("build_dir", type=Path, help="Build directory containing manifest.json and Companion_Setup.exe")
    args = parser.parse_args()
    load_dotenv()

    pem = os.environ.get("PRIVATE_KEY")
    if not pem:
        parser.error("PRIVATE_KEY must contain the PEM signing key")

    manifest_path = args.build_dir / "manifest.json"
    data = manifest_path.read_bytes()
    manifest = json.loads(data)
    installer = (args.build_dir / "Companion_Setup.exe").read_bytes()
    if (hashlib.sha256(installer).hexdigest() != manifest["sha256"]
            or len(installer) != manifest["size"]):
        raise ValueError("Installer does not match manifest")

    private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("PRIVATE_KEY must be an Ed25519 key")
    signature = private_key.sign(data)
    (args.build_dir / "manifest.sig").write_bytes(signature)
    print("Manifest signed.")


if __name__ == "__main__":
    main()

