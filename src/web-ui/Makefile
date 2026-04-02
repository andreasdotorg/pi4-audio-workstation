.PHONY: test-unit test-integration-browser test-integration-browser-headed test-visual test-all \
       update-snapshots install-test-deps

test-unit:
	python -m pytest tests/ -v -k "not e2e"

test-integration-browser:
	python -m pytest tests/integration/ -v

test-integration-browser-headed:
	python -m pytest tests/integration/ -v --headed

test-visual:
	python -m pytest tests/integration/test_visual_regression.py -v

# Regenerate reference screenshots after intentional UI changes.
# Review the diffs in tests/integration/screenshots/ before committing.
update-snapshots:
	python -m pytest tests/integration/test_visual_regression.py -v --update-snapshots

test-all: test-unit test-integration-browser

install-test-deps:
	pip install playwright pytest pytest-playwright numpy
	playwright install chromium
