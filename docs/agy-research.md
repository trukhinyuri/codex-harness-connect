# agy / Antigravity CLI: доказательная карта

Срез: 1 октября 2026, 05:51 Europe/Amsterdam (03:51 UTC). Исследование по `frontier-research`. Done: проверить официальный CLI, механизм делегирования Hermes, жизненный цикл и договорную границу будущего локального Codex plugin. Установок, изменений auth/config/security и запросов к модели не было. Проверка документальная; поведение установленного у пользователя `agy` не проверялось.

**Вывод:** Google документирует полноценный программный headless интерфейс `agy`, включая NDJSON, несколько ходов и восстановление разговора. Hermes использует его как внешний worker через terminal/process, а не как собственный orchestration API. Однако текущие Google terms прямо ограничивают доступ сторонними продуктами; локальный Codex plugin с Antigravity subscription OAuth нельзя объявлять разрешённым только потому, что он запускает официальный binary.

## 1. Подтверждённый CLI

[Google Headless mode](https://www.antigravity.google/docs/cli/headless/) — разделы Output formats, Stream prompts from stdin, Flag reference:

| Поверхность | Точная форма |
|---|---|
| Один prompt | `agy -p "<prompt>"`; aliases `--print`, `--prompt` |
| Ответ | `--output-format text\|json\|stream-json`, default `text` |
| Несколько ходов | `agy --input-format stream-json --output-format stream-json` |
| Schema | `--json-schema`: JSON строка, путь файла, primitive type |
| Модель | `--model <slug>`; каталог `agy models` |
| Reasoning | `--effort low\|medium\|high` |
| Агент | `--agent <name>`; каталог `agy agents` |
| Deadline | `--print-timeout <duration>`, default `5m` |

`stdout` содержит ответ/события, `stderr` — диагностику. JSON даёт `conversation_id`, `status`, `response`, `error`, `duration_seconds`, `num_turns`, `usage`; schema добавляет `structured_output`, `json_schema`. NDJSON: `init` → `step_update` → `result`. Progress включает `ACTIVE`/`DONE`, `step_index`, `step_type`, `text_delta`, `tool_info`, `subagent_info` и usage. Статусы: `SUCCESS`, `ERROR`, `CANCELED`, `INTERRUPTED`, `INVALID`, `WAITING`, `RUNNING`.

Streaming input принимает `{"event":"user","message":{"content":"<prompt>"}}`. Следующий prompt — после `result`. `response` относится к ходу; counters накопительные. Закрытие stdin завершает процесс после текущего хода. `control_request`/`control_response` отвергаются с exit `2`; CLI slash-команды, например `/model`, также не подходят этому потоку. Неизвестная модель даёт ошибку. Approval может быть soft-denied при exit `0`.

**Вывод для адаптера:** читать оба потока; отсутствие `result`, ошибка протокола, exit процесса и выполнение предметных критериев должны проверяться отдельно. `SUCCESS` означает полученный ответ, а не доказанное выполнение порученной работы. Универсального RPC cancel/approval в этом stdin-протоколе не подтверждено. Утверждение Hermes «print только plain text» опровергнуто текущим официальным источником.

## 2. Resume и интерактивный lifecycle

[Google Resume](https://www.antigravity.google/docs/cli/commands/resume/), разделы Command-line shortcuts и session cache:

- `--continue` / `-c` выбирает последний разговор активного workspace.
- `--conversation <id>` задаёт конкретный разговор; ID следует сохранять из результата запуска.
- Cache: `~/.gemini/antigravity-cli/cache/last_conversations.json`, ключ — абсолютный workspace path. Backend проверяет наличие разговора; отсутствующий/удалённый последний разговор может привести к новой сессии.
- `/resume` (aliases `/switch`, `/conversation`) — интерактивный picker. `/fork` создаёт другую ветвь разговора. Возобновление контекста не означает сохранение старого OS процесса.

[Google CLI reference](https://www.antigravity.google/docs/cli/reference/), Core slash commands и Global controls:

- `/agents` показывает агентов; `/tasks` — фоновые shell tasks; `/usage` / `/quota` — quota; `/exit` / `/quit` — выход.
- `Esc` останавливает активный stream или закрывает панель; `Ctrl+C` завершает session, с подтверждением при работающем агенте; `Ctrl+D` выходит при пустом prompt.

**Вывод для адаптера:** хранить внешний job ID, OS PID/process group, workspace и `conversation_id` раздельно. Для параллельных jobs выбирать явный `--conversation`, поскольку «последний» может смениться. При принудительном OS завершении отдельно проверять выход потомков и сохранность файлов; документация не обещает rollback или автоматическое прекращение всех удалённых работ.

## 3. Что действительно делает Hermes

Проверенная версия исходников: [commit af92ea8e5b852518c523c3e8b2cbd95f0f3d79dc](https://github.com/NousResearch/hermes-agent/commit/af92ea8e5b852518c523c3e8b2cbd95f0f3d79dc), timestamp 2026-10-01T03:30:18Z. Сетевой readback по SHA выполнен; локальные копии лежат в `work/agy-sources/`.

[Hermes antigravity-cli SKILL v0.2.0](https://github.com/NousResearch/hermes-agent/blob/af92ea8e5b852518c523c3e8b2cbd95f0f3d79dc/optional-skills/autonomous-ai-agents/antigravity-cli/SKILL.md), строки 16–112:

- Это optional skill с процедурами вызова binary через Hermes `terminal`; не сетевой SDK и не собственная Antigravity auth реализация.
- Одно поручение — `agy -p`; длинное — background process, затем poll/log/wait.
- Разговорный TUI — PTY и при необходимости tmux `capture-pane` / `send-keys`; bare `agy` или `-i`.
- Параллельные независимые поручения — один Git worktree и независимый `agy -p` на задачу.
- `--add-dir` описан как repeatable context root. Это подтверждено Hermes guide; в прочитанной официальной headless flag table его нет, установленный `agy help` не проверялся.
- Skill отделяет worker backend от orchestration. В нём всё ещё присутствует неверное ограничение отсутствия JSON. Отсутствие `--max-turns` заявлено Hermes; официальная headless table его не документирует.

[Hermes terminal_tool.py](https://github.com/NousResearch/hermes-agent/blob/af92ea8e5b852518c523c3e8b2cbd95f0f3d79dc/tools/terminal_tool.py), строки 1514–1627:

Текущий публичный tool interface предпочитает `background=true, notify=true`; legacy `notify_on_complete` ещё принимается. PTY требует background и поддерживается local backend. `persist_on_release` по умолчанию false; true сохраняет job через lifecycle cleanup агента, но не гарантирует выживание после выхода host process. Это отдельная настройка, не обязательный способ запуска agy.

[Hermes process_registry.py](https://github.com/NousResearch/hermes-agent/blob/af92ea8e5b852518c523c3e8b2cbd95f0f3d79dc/tools/process_registry.py), строки 2094–2205, 2224–2430, 2630–2749:

`process_manage` предоставляет `list`, `poll`, `log`, `wait`, `kill`, `write`, `submit`, `close`, `handoff`. `poll` показывает running/exited, PID, uptime и output; `wait` timeout сохраняет running process. `write` отправляет сырые данные, `submit` добавляет newline, `close` даёт EOF stdin. `kill` завершает process/потомков с escalation. Сохранённые результаты после restart — не гарантия сохранения полной истории или живого runtime handle. Subagent-owned процессы обычно прекращаются при завершении владельца; `handoff` передаёт ownership родителю.

**Вывод:** Hermes process session ID относится к оболочке; agy conversation ID — к разговору. Уведомление о выходе процесса не заменяет анализ agy результата и тестов.

[Hermes model-provider plugin docs](https://github.com/NousResearch/hermes-agent/blob/af92ea8e5b852518c523c3e8b2cbd95f0f3d79dc/website/docs/developer-guide/model-provider-plugin.md), строки 9–23, 247–296: generic extension допускает stdio-backed provider с `auth_type="external_process"` и `create_client`; in-tree пример — Copilot ACP. Это доказывает механизм расширения Hermes, но не Google разрешение и не готовый официально поддерживаемый agy provider. Не следует превращать optional skill в свидетельство полноценного inference adapter.

## 4. Native agents, teams и worktrees

[Google Custom subagents](https://www.antigravity.google/docs/subagents/), Invoking subagents, lifecycle, inheritance:

Агент вызывает `invoke_subagent`; workspace options `inherit`, `branch` (Git worktree), `share`. История родителя не копируется в новый context. Состояния Running → Idle либо Killed; сообщение будит Idle с сохранением собственного контекста. Killed не будится; временные worktrees автоматически очищаются. Parent/subagents могут общаться по conversation IDs; nesting ограничен десятью уровнями. `/agents` показывает status и текущий step; `k` останавливает выбранного subagent. Safety scopes наследуются внутри Antigravity hierarchy — это не доказательство наследования Codex policy внешним процессом.

[Google Teamwork](https://www.antigravity.google/docs/teamwork/): `/teamwork-preview <task>` (alias `/teamwork`) доступен на paid plans. Сначала scoping interview и prompt artifact, затем отдельное подтверждение исполнения; после него Sentinel/Orchestrator распределяют Workers/Explorers и reviewers. Progress хранится в project-plan/progress artifacts и показывается UI/status bar. Default workspace `~/teamwork_projects/{PROJECT_NAME}`, exclusive file ownership и scratch для агентов. Это native coordinator. Документация не устанавливает внешний headless teams API с командами create/status/cancel/resume и не гарантирует, что интерактивный interview можно надёжно выполнить через print.

**Вывод:** worktree fan-out внешнего plugin и native Teamwork — два разных механизма. Для адаптера обоснованы отдельные process jobs в подготовленных worktrees; wrapper должен сам обеспечить ownership, concurrency, review и cleanup. Native Teamwork требует отдельной проверки интерфейса и режима авторизации, а не простой подстановки `/teamwork-preview` в streaming stdin.

## 5. Permissions и auth

[Google Permissions](https://www.antigravity.google/docs/permissions/), CLI fine-grained permissions и defaults: правила `action(target)`; приоритет Deny > Ask > Allow. Workspace file read/write auto-allowed; command/MCP/non-workspace access обычно Ask. Prompt «только read-only» сам по себе не создаёт enforced read-only boundary.

[Google Terminal sandbox](https://www.antigravity.google/docs/sandbox/), именно CLI configuration: `enableTerminalSandbox` default false, `toolPermission` default request-review; `--sandbox` включает isolation на запуск. Workspace writable; read scopes могут быть readonly; network определяется grants; возможны согласованные unsandboxed escape hatches. `--dangerously-skip-permissions` из headless docs auto-approves все запросы — unsuitable default для будущего plugin. Ни одна проверка здесь не меняла эти настройки.

[Google Installation/auth](https://www.antigravity.google/docs/cli/install/): официальный binary использует OS keyring и browser/SSH sign-in. Headless при отсутствии cached auth завершает ошибкой вместо unattended sign-in. Отдельный документированный режим Gemini API: `modelProvider: "gemini"` вместе с `GEMINI_API_KEY`; requests идут непосредственно Gemini API, account session не создаётся. Это другая auth/billing route, не способ перераспределить Antigravity subscription quota; она требует отдельного разрешённого scope и условий API. В данном исследовании не использовалась.

## 6. Договорная граница Codex plugin

[Google Antigravity Additional Terms](https://www.antigravity.google/terms), §§1, 4–6:

- §6 запрещает доступ к Service через third-party software/tools/services, с примером OpenClaw + Antigravity OAuth; возможны suspension/termination Antigravity и/или Gemini CLI accounts.
- §4 возлагает на пользователя ответственность за AI-agent actions и доступы; §5 описывает обработку Interactions и настройку участия в улучшении моделей.
- Для перечисленных Enterprise/Workspace/API-key enterprise путей вводная часть отсылает к договору администратора вместо этих additional terms.

**Неопределённость:** Google Headless официально описывает программы, CI и Python subprocess, а §6 написан широко. Прочитанные Google источники не содержат явного исключения «Codex/Hermes локально запускает официальный agy, поэтому subscription OAuth разрешён». Официальная headless возможность — техническое доказательство, не достаточное договорное разрешение стороннего inference bridge. Нельзя утверждать ни blanket permission для wrapper, ни подтверждённое разрешение reverse-engineered OAuth/Cloud Code endpoints. Вопрос снимается прямым Google разъяснением либо применимым договором.

| Маршрут | Установленный статус |
|---|---|
| Пользователь запускает официальный agy TUI/headless на своём аккаунте | Документированный Google product interface; применимы terms и права аккаунта |
| Codex plugin → official agy subprocess → subscription OAuth | Технически соответствует stdio surface; договорная допустимость не подтверждена, §6 — существенное препятствие |
| Third-party provider напрямую переиспользует Antigravity OAuth/недокументированные endpoints | §6 прямо против доступа сторонними tools; одобрение не найдено |
| Native agy teams/Remote Control | Официальные product features при доступном плане/policy; не внешний Codex API |
| agy с собственным Gemini API key | Документирован отдельный provider/auth path; не subscription workaround, billing/terms должны быть проверены отдельно |
| Enterprise route | Проверять применимый договор администратора; general terms автоматически не переносить |

## 7. Remote Control не является job API

[Google Remote Control](https://www.antigravity.google/docs/remote-control/) документирует `agy --remote-control` и `/remote-control on|off` для текущей TUI session, а также `agy remote-control start|status|stop` и `start --name <name>` для OS daemon. Это управление официальным remote UI, не status/cancel отдельного coding job. На macOS daemon — LaunchAgent, запускается при login и прекращается при logout; start/stop меняют OS service state. Ничего из этого не запускалось.

## Проверка, пробелы, следующий шаг

Done для исследовательской подзадачи достигнут: интерфейсы и ограничения сведены по первоисточникам, Hermes implementation закреплена SHA, главный контраргумент (terms) проверен прямым HTML readback. Подтверждены ошибочные рекомендации старого Hermes skill, которые нельзя копировать в новый plugin.

Runtime acceptance остаётся будущим этапом: проверить installed `agy --version`/`help` без model call, затем только в разрешённом scope один bounded smoke test, cancellation с подтверждением остановки потомков, resume по explicit ID и обработку soft-denial. До исполнения subscription-backed Codex wrapper требуется закрыть terms ambiguity. Недельная квота централизованно проверяется ведущим агентом; расход этой подзадачи отдельно неизвестен. Пилот навыка: наблюдаемый Done — карта; обнаруженный существенный пропуск — stale Hermes JSON guidance; объективная проверка — свежие Google HTML и pinned source; модельная проверка не выполнялась.
