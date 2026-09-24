# The three shortest SWE-bench Verified tasks

Written 2026-09-18. SWE-bench Verified is 500 real GitHub issues from Python repos (django,
sympy, scikit-learn, ...). The agent gets the repo checked out just before the real fix, plus
the issue text, and must change the code so the hidden tests from the real pull request pass.
Unlike Terminal-Bench, the repo's own test suite is visible, so the agent spends its time
running pytest and reading tracebacks. That makes it a better fit for judging a Bash tool swap.

Ranked by lines changed in the reference fix, then by issue length. All three fixes are a
single added line.

To rebuild the ranking: download the task folders (text only, ~10 s) and count changed lines
in each `solution/solve.sh`.

```bash
harbor datasets download swe-bench/swe-bench-verified@latest -o /tmp/swe-tasks
cd /tmp/swe-tasks/swe-bench-verified
for t in */; do echo "$(grep -c -E '^[+-][^+-]' $t/solution/solve.sh) $(wc -w < $t/instruction.md) $t"; done | sort -n | head
```

Gotchas that apply to every SWE-bench task:

- Images are prebuilt on Docker Hub (`swebench/sweb.eval.x86_64.*`) and Intel-only.
  `run_mcp_bash.sh` sets `DOCKER_DEFAULT_PLATFORM=linux/amd64` so Apple Silicon runs them
  under emulation. Expect a slow first pull and slower test runs.
- Task names carry a `swe-bench/` prefix, so the task filter needs a leading `*` (for example `'*django-11179'`), or Harbor reports "No tasks matched".
- Django tasks use Django's own test runner (`./tests/runtests.py`), not pytest.

## 1. `scikit-learn__scikit-learn-14141` — pytest

- **Issue:** "Add joblib in show_versions." Two sentences. `sklearn.show_versions()` prints
  the versions of dependencies, and joblib is missing from the list.
- **Fix:** add `"joblib"` to a list in `sklearn/utils/_show_versions.py`.
- **Grader:** 1 test must go from failing to passing, 2 must keep passing. Test file is
  `sklearn/utils/tests/test_show_versions.py`.
- **Why pick it:** smallest task in the dataset and the only one of the three graded with
  plain pytest. Image is large (compiled scikit-learn, numpy, scipy).
- **Run:** `DATASET=swe-bench/swe-bench-verified@latest ./run_mcp_bash.sh '*scikit-learn-14141' mcpbash-sklearn-14141`

## 2. `django__django-11179` — Django test runner

- **Issue:** calling `.delete()` on a model instance with no relations does not reset the
  instance's primary key to `None`. The issue text even names the file and line.
- **Fix:** one `setattr(...)` in `django/db/models/deletion.py`.
- **Grader:** 1 test must go from failing to passing, 40 must keep passing.
- **Why pick it:** smaller image than scikit-learn (Django is pure Python). Good second task.
- **Run:** `DATASET=swe-bench/swe-bench-verified@latest ./run_mcp_bash.sh '*django-11179' mcpbash-django-11179`

## 3. `django__django-15741` — Django test runner

- **Issue:** `django.utils.formats.get_format()` crashes with a `TypeError` when passed a lazy
  translated string, such as `some_date|date:_('Y-m-d')` in a template.
- **Fix:** one `str(...)` call in `django/utils/formats.py`.
- **Grader:** 2 tests must go from failing to passing, 104 must keep passing. Largest
  regression surface of the three, so the agent has the most test output to read.
- **Run:** `DATASET=swe-bench/swe-bench-verified@latest ./run_mcp_bash.sh '*django-15741' mcpbash-django-15741`
