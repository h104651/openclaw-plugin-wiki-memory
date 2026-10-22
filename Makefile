.PHONY: test index recall stats

export PYTHONPATH := $(PWD)/src:$(PYTHONPATH)

test:
	python3 -m unittest discover -s tests -v
	node --test tests/test_plugin.mjs

index:
	python3 -m astor_wiki_memory index --rebuild

recall:
	python3 -m astor_wiki_memory recall "OpenClaw LanceDB Pro replacement strategy" --limit 5

stats:
	python3 -m astor_wiki_memory stats

