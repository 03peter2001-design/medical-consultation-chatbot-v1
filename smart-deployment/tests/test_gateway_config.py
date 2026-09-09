import re
import unittest
from pathlib import Path

CONFIG = (
    Path(__file__).resolve().parents[1] / "smart-launcher-gateway.conf"
).read_text(encoding="utf-8")
FHIR_PROXY_CONFIG = (Path(__file__).resolve().parents[1] / "fhir-proxy.conf").read_text(
    encoding="utf-8"
)
SMART_COMPOSE_CONFIG = (
    Path(__file__).resolve().parents[2] / "compose.smart.yml"
).read_text(encoding="utf-8")


class SmartLauncherGatewayConfigTests(unittest.TestCase):
    def test_allows_headers_used_by_no_store_fhir_requests(self) -> None:
        match = re.search(
            r'Access-Control-Allow-Headers\s+"([^"]+)"',
            CONFIG,
        )
        self.assertIsNotNone(match)
        allowed = {item.strip().lower() for item in match.group(1).split(",")}
        self.assertTrue(
            {"authorization", "accept", "cache-control", "pragma"} <= allowed
        )

    def test_cors_origin_remains_limited_to_loopback_http_origins(self) -> None:
        self.assertIn(r"~^http://127\.0\.0\.1:[0-9]+$", CONFIG)
        self.assertIn(r"~^http://localhost:[0-9]+$", CONFIG)
        self.assertNotIn("Access-Control-Allow-Origin *", CONFIG)

    def test_hapi_pagination_base_has_an_exact_compatibility_alias(self) -> None:
        self.assertRegex(FHIR_PROXY_CONFIG, r"location\s+=\s+/fhir\s*{")
        self.assertIn("proxy_pass http://hapi:8080/fhir;", FHIR_PROXY_CONFIG)

    def test_backend_issuer_tracks_the_public_launcher_port(self) -> None:
        self.assertIn(
            'FHIR_PUBLIC_ISSUER: "http://127.0.0.1:'
            '${SMART_LAUNCHER_PORT:-8090}/v/r4/fhir"',
            SMART_COMPOSE_CONFIG,
        )


if __name__ == "__main__":
    unittest.main()
