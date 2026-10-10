"""Presentation regressions without importing GUI or starting app services."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_method(filename, name, namespace):
    # Isolate view logic from module imports, which initialize browser and database services.
    tree = ast.parse((ROOT / "ui" / filename).read_text(encoding="utf-8"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class PresentationTests(unittest.TestCase):
    def test_all_ui_modules_parse(self):
        for path in (ROOT / "ui").glob("*.py"):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"))

    def test_small_text_has_readable_contrast(self):
        tree = ast.parse((ROOT / "ui/components.py").read_text(encoding="utf-8"))
        colors = next(ast.literal_eval(n.value) for n in tree.body
                      if isinstance(n, ast.Assign) and n.targets[0].id == "C")

        def luminance(hex_color):
            rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
            return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for foreground in ("text", "body", "secondary", "tertiary", "muted", "ash"):
            for background in ("canvas", "card", "input", "elevated"):
                with self.subTest(foreground=foreground, background=background):
                    contrast = (luminance(colors[foreground]) + 0.05) / (luminance(colors[background]) + 0.05)
                    self.assertGreaterEqual(contrast, 4.5)

    def test_loading_does_not_invent_scores_skills_or_locations(self):
        records = [{"url": "one", "score": 10, "role": "Engineer", "company": "Example"}]
        selected = []
        view = SimpleNamespace(all_jobs=[], filtered_jobs=[], selected_job=None,
                               select_opportunity=selected.append)
        view.apply_filters = lambda: setattr(view, "filtered_jobs", view.all_jobs)
        method = load_method("suggestions_view.py", "load_suggestions_table", {
            "get_suggested_jobs": lambda: records,
            "log_message": lambda message: self.fail(message),
        })
        method(view)
        self.assertEqual(records, [{"url": "one", "score": 10, "role": "Engineer", "company": "Example"}])
        self.assertEqual(selected, records)

    def test_empty_results_clear_stale_selection(self):
        cleared = []
        view = SimpleNamespace(all_jobs=[], filtered_jobs=[], selected_job={"url": "old"},
                               apply_filters=lambda: None, _render_empty_detail_panel=lambda: cleared.append(True))
        method = load_method("suggestions_view.py", "load_suggestions_table", {
            "get_suggested_jobs": lambda: [], "log_message": lambda message: self.fail(message),
        })
        method(view)
        self.assertIsNone(view.selected_job)
        self.assertEqual(cleared, [True])

    def test_remote_filter_uses_role_or_recorded_location_not_company(self):
        view = SimpleNamespace(
            search_var=SimpleNamespace(get=lambda: ""), current_filter="Remote",
            all_jobs=[{"role": "Engineer", "company": "Remote Corp", "location": "London"},
                      {"role": "Engineer", "company": "Example", "location": "Remote"}],
            badge_found=SimpleNamespace(configure=lambda **kwargs: None), render_cards=lambda: None,
        )
        method = load_method("suggestions_view.py", "apply_filters", {"CONFIG": {"settings": {"min_score": 70}}})
        method(view)
        self.assertEqual(view.filtered_jobs, [view.all_jobs[1]])


if __name__ == "__main__":
    unittest.main()
