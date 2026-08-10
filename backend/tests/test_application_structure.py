import ast
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


class ApplicationStructureTests(unittest.TestCase):
    def test_backend_root_has_only_the_asgi_python_entrypoint(self):
        root_python_files = {path.name for path in BACKEND_DIR.glob("*.py")}
        self.assertEqual(root_python_files, {"main.py"})

    def test_entrypoint_stays_thin(self):
        source = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        functions = [
            node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(functions, [])
        self.assertLessEqual(len(source.splitlines()), 10)

    def test_application_is_only_router_composition(self):
        source = (BACKEND_DIR / "app" / "factory.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertEqual(functions, {"create_app"})
        self.assertIn(
            "app.include_router(system_router, prefix=API_V1_PREFIX)",
            source,
        )
        self.assertIn(
            "app.include_router(patient_router, prefix=API_V1_PREFIX)",
            source,
        )
        self.assertIn(
            "app.include_router(doctor_router, prefix=API_V1_PREFIX)",
            source,
        )
        self.assertEqual(source.count("include_in_schema=False"), 3)

    def test_routes_remain_grouped_by_feature(self):
        expected = {
            "app/routes/system.py": {
                ("GET", "/health"),
                ("POST", "/transcribe"),
                ("GET", "/avatar/status"),
                ("POST", "/avatar/warmup"),
                ("POST", "/avatar/speak"),
            },
            "app/routes/patient.py": {("POST", "/chat")},
            "app/routes/doctor.py": {
                ("GET", "/rules"),
                ("GET", "/terminology/snomed"),
                ("POST", "/rules/authorize"),
                ("POST", "/rules/assistant"),
                ("PUT", "/rules/safety"),
                ("PUT", "/rules/fact-labels"),
                ("PUT", "/rules/disease-profiles/{route}"),
                ("GET", "/consultations"),
                ("DELETE", "/consultations/{consultation_id}"),
                ("POST", "/load_patient"),
                ("DELETE", "/patient/{session_id}"),
                ("POST", "/chat"),
                ("DELETE", "/session/{session_id}"),
            },
        }

        for filename, expected_routes in expected.items():
            tree = ast.parse((BACKEND_DIR / filename).read_text(encoding="utf-8"))
            actual = set()
            for node in tree.body:
                if not isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name)
                        and decorator.func.value.id == "router"
                        and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                    ):
                        actual.add(
                            (
                                decorator.func.attr.upper(),
                                decorator.args[0].value,
                            )
                        )
            self.assertEqual(actual, expected_routes, filename)


if __name__ == "__main__":
    unittest.main()
