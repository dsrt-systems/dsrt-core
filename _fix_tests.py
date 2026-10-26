"""Fix 3 test logic bugs in test_c9_integration.py."""
import pathlib

p = pathlib.Path("tests/test_c9_integration.py")
content = p.read_text(encoding="utf-8")

# Fix 1: _run() helper — empty dict is falsy, use `is not None`
content = content.replace(
    '"metrics": metrics or {',
    '"metrics": metrics if metrics is not None else {'
)

# Fix 2: test_complete — without policy, both candidates are eligible
content = content.replace(
    "assert r.candidates_after_policy == 1\n\n    def test_with_policy",
    "assert r.candidates_after_policy == 2\n\n    def test_with_policy"
)

# Fix 3: test_custom_id — mock extractor must respect task_id argument
# Replace the simple return_value with a side_effect that uses the real task_id
old_runner = '''    def _runner(self, **ov):
        ext = MagicMock()
        ext.extract.return_value = _reqs()'''

new_runner = '''    def _runner(self, **ov):
        ext = MagicMock()
        def _extract_side_effect(task_id, description, **kw):
            return _reqs(task_id=task_id, description=description)
        ext.extract.side_effect = _extract_side_effect'''

content = content.replace(old_runner, new_runner)

p.write_text(content, encoding="utf-8")
print(f"Fixed tests/test_c9_integration.py ({len(content)} bytes)")
