# Notes for AI coding agents (Claude Code and similar)

Open-source dashboard for yi-hack cameras: FastAPI + Jinja2/HTMX in `app/`, MediaMTX for live video.
Read `README.md` first.

- Never commit real configuration or secrets: `.env`, `config.yml` and `mediamtx/mediamtx.yml` are
  gitignored. Examples use placeholder IPs (`192.168.1.50`, `192.168.1.51`) and generic names.
- Every user-facing string goes through `app/i18n.py` (`t("key")` in templates and Python, `T("key")` in
  page scripts) with both English and Italian text; `tests/test_i18n.py` fails if one is missing.
- Keep it light: no Node/build step, no new services. The vendored JS lives in `app/static/vendor/`.
- Before committing, run the linter and the tests (commands in README → Tests and linter). CI runs the same.
- Log messages and code comments in English. Never log tokens or URLs that can contain them.
