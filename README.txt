ClipsBot — все правки одним набором.

КУДА КЛАСТЬ (в корень репозитория ClipsBot, с заменой существующих файлов):

  clipper/__main__.py            -> clipper/__main__.py
  clipper/bundles.py             -> clipper/bundles.py          (НОВЫЙ)
  clipper/cuts.py                -> clipper/cuts.py             (НОВЫЙ)
  clipper/diagnose.py            -> clipper/diagnose.py         (НОВЫЙ)
  clipper/decisions.py           -> clipper/decisions.py
  clipper/framing.py             -> clipper/framing.py
  clipper/judge.py               -> clipper/judge.py
  clipper/learn.py               -> clipper/learn.py
  clipper/llm.py                 -> clipper/llm.py
  clipper/pipeline.py            -> clipper/pipeline.py
  clipper/platforms/instagram.py -> clipper/platforms/instagram.py
  clipper/platforms/tiktok.py    -> clipper/platforms/tiktok.py
  clipper/poster.py              -> clipper/poster.py
  clipper/render.py              -> clipper/render.py
  clipper/stats.py               -> clipper/stats.py
  clipper/twitch.py              -> clipper/twitch.py
  config.yaml                    -> config.yaml
  docs/index.html                -> docs/index.html             (дашборд: кнопки)

Папки в репозитории: clipper/ (код), clipper/platforms/ (площадки), docs/ (дашборд), корень (config.yaml).
Файлы в .github/ менять не нужно.

ПОСЛЕ ЗАМЕНЫ:
1. Commit и push в ветку main.
2. Settings → Secrets: GEMINI_API_KEY (ключ из проекта с billing).
3. Actions → «2 · Process» → Run workflow (проверить, что в логе строка «ИИ-провайдеры: gemini-...»).
4. Actions → «3 · Post» → Run workflow.
5. Диагностика: локально `python -m clipper diagnose` или вручную запустить через Actions.
