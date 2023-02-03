COMMON_LINT_PATHS = tool.py
ALL_LINT_PATHS = $(COMMON_LINT_PATHS)
ISORT_PARAMS = --ignore-whitespace --skip-glob '*/node_modules/*' $(ALL_LINT_PATHS)
ISORT_CHECK_PARAMS = --diff --check-only

lint:
	isort $(ISORT_PARAMS) $(ISORT_CHECK_PARAMS)
	ruff $(ALL_LINT_PATHS)
	unify --check-only --recursive $(ALL_LINT_PATHS)
	double-indent --dry-run $(ALL_LINT_PATHS)
	flake8 $(ALL_LINT_PATHS)
	mypy $(COMMON_LINT_PATHS) --install-types --non-interactive
	pylint --rcfile .pylint.rc $(ALL_LINT_PATHS)


format:
	ruff $(ALL_LINT_PATHS) --fix
	isort $(ISORT_PARAMS)
	unify --in-place --recursive $(ALL_LINT_PATHS)
	double-indent $(ALL_LINT_PATHS)
