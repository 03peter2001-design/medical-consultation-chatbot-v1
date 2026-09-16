import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONFIG = (
    Path(__file__).resolve().parents[1] / "smart-launcher-gateway.conf"
).read_text(encoding="utf-8")
FHIR_PROXY_CONFIG = (Path(__file__).resolve().parents[1] / "fhir-proxy.conf").read_text(
    encoding="utf-8"
)
SMART_COMPOSE_CONFIG = (
    Path(__file__).resolve().parents[2] / "compose.smart.yml"
).read_text(encoding="utf-8")
START_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "start-smart.sh"
).read_text(encoding="utf-8")
SMART_APP_DIR = Path(__file__).resolve().parents[2] / "smart-app"
START_PAGE_TEMPLATE = (SMART_APP_DIR / "start.html").read_text(encoding="utf-8")


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


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

    def test_start_script_uses_configurable_fhir_port_with_repo_default(self) -> None:
        self.assertIn('FHIR_PORT="${FHIR_PORT:-8081}"', START_SCRIPT)
        self.assertIn(
            'FHIR_BASE_URL="http://127.0.0.1:${FHIR_PORT}/fhir"', START_SCRIPT
        )
        self.assertNotIn('FHIR_BASE_URL="http://127.0.0.1:8080/fhir"', START_SCRIPT)

    def test_start_script_validates_all_externally_supplied_ports(self) -> None:
        for variable in ("FHIR_PORT", "SMART_APP_PORT", "SMART_LAUNCHER_PORT"):
            self.assertIn(f'validate_port "{variable}" "${{{variable}}}"', START_SCRIPT)

    def test_start_page_links_are_rendered_from_runtime_ports(self) -> None:
        rendered = START_PAGE_TEMPLATE.replace("${SMART_APP_PORT}", "15175").replace(
            "${SMART_LAUNCHER_PORT}", "18090"
        )
        collector = _LinkCollector()
        collector.feed(rendered)

        self.assertEqual(len(collector.links), 2)
        for link in collector.links:
            launcher_url = urlparse(link)
            self.assertEqual(launcher_url.hostname, "127.0.0.1")
            self.assertEqual(launcher_url.port, 18090)
            launch_uri = parse_qs(launcher_url.query)["launch_uri"]
            self.assertEqual(launch_uri, ["http://127.0.0.1:15175/launch.html"])

    def test_smart_app_uses_nginx_runtime_template_for_start_page(self) -> None:
        self.assertIn(
            "./smart-app/start.html:/etc/nginx/templates/start.html.template:ro",
            SMART_COMPOSE_CONFIG,
        )
        self.assertIn(
            "NGINX_ENVSUBST_OUTPUT_DIR: /usr/share/nginx/html", SMART_COMPOSE_CONFIG
        )
        self.assertIn('SMART_APP_PORT: "${SMART_APP_PORT:-5174}"', SMART_COMPOSE_CONFIG)
        self.assertIn(
            'SMART_LAUNCHER_PORT: "${SMART_LAUNCHER_PORT:-8090}"',
            SMART_COMPOSE_CONFIG,
        )

    def test_external_runtime_images_are_reproducibly_pinned(self) -> None:
        self.assertNotRegex(SMART_COMPOSE_CONFIG, r"image:\s+[^\n]*:latest(?:\s|$)")
        self.assertEqual(SMART_COMPOSE_CONFIG.count("image: nginx:1.27.5-alpine"), 2)
        self.assertIn(
            "image: smartonfhir/smart-launcher-2@sha256:"
            "72bd3e3c682ce4c74e6dddb605d89acad7c8aae446ae38079e8dfe8455b84793",
            SMART_COMPOSE_CONFIG,
        )

    def test_launch_pages_require_pkce_and_granular_read_scopes(self) -> None:
        expected_resources = {
            "Patient.r",
            "Encounter.rs",
            "Condition.rs",
            "Observation.rs",
            "AllergyIntolerance.rs",
            "MedicationRequest.rs",
            "MedicationStatement.rs",
            "Procedure.rs",
            "QuestionnaireResponse.rs",
        }
        for name, context_scope in (
            ("launch.html", "launch"),
            ("launch-patient.html", "launch/patient"),
        ):
            page = (SMART_APP_DIR / name).read_text(encoding="utf-8")
            self.assertIn('pkceMode: "required"', page)
            self.assertNotIn("patient/*.read", page)
            scope_match = re.search(r'scope:\s*\n?\s*"([^"]+)"', page)
            self.assertIsNotNone(scope_match)
            scopes = set(scope_match.group(1).split())
            self.assertIn(context_scope, scopes)
            self.assertEqual(
                {
                    scope.removeprefix("patient/")
                    for scope in scopes
                    if scope.startswith("patient/")
                },
                expected_resources,
            )


if __name__ == "__main__":
    unittest.main()
