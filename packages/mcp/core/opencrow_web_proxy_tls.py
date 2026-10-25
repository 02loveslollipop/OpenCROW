"""Per-session CA; never modifies system trust or disables upstream verification."""
from __future__ import annotations
import datetime
import hashlib
import ipaddress
import ssl
from pathlib import Path
from opencrow_web_proxy_store import private_dir, write_private


def server_context(directory: Path, host: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    private_dir(directory)
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_path, key_path = directory / "ca.pem", directory / "ca-key.pem"
    if not ca_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenCROW isolated proxy CA")])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=7))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True).sign(key, hashes.SHA256()))
        write_private(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        write_private(ca_path, ca.public_bytes(serialization.Encoding.PEM))
    ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    prefix = hashlib.sha256(host.encode()).hexdigest()
    cert_path, leaf_key_path = directory / (prefix + ".pem"), directory / (prefix + "-key.pem")
    if not cert_path.exists():
        leaf = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host[:64])])
        try: san = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError: san = x509.DNSName(host)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(ca.subject).public_key(leaf.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False).sign(key, hashes.SHA256()))
        write_private(leaf_key_path, leaf.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        write_private(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_alpn_protocols(["http/1.1"])
    context.load_cert_chain(cert_path, leaf_key_path)
    return context
