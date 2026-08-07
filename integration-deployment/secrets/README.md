# Runtime secrets

Place these host-managed files here before deployment:

- `ucc-jwt-public.pem`: RS256 public key exported from the UCC signing certificate.
- `tls-fullchain.pem`: certificate chain for the patient and internal API DNS names.
- `tls-private-key.pem`: TLS private key, readable only by the deployment administrator.

The directory is ignored by Git except for this file. Never copy the UCC RS256
private key to Ubuntu; it stays in the Windows Certificate Store.

