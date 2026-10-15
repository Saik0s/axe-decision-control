# Select a tree provider and data boundary

| Provider/model | API base | Supported tree route |
| --- | --- | --- |
| OpenRouter `typesafe/jev-1.14` | `https://openrouter.ai/api` | Typed `/alpha/decisions`; text+image capable, tree supplies accessibility text |
| OpenRouter `cloudflare/clef` | `https://openrouter.ai/api` | Typed `/alpha/decisions` |
| OpenRouter `typesafe/jev-1.13` | `https://openrouter.ai/api` | Historical text-only adapter route at `/alpha/decisions` |
| Winnow `Winnow-12B` | `http://127.0.0.1:8091` by default | Typed `/v1/systemone` |

These describe the bundled adapter contract, not current account availability or
service readiness. Select an explicit model, API base, and service port. Do not
append the endpoint path to the base. Do not silently switch providers. Local
Winnow is a caller-managed service, not hosted JeV running locally.

Version context, 2026-10-15: the [OpenRouter JeV 1.14 listing](https://openrouter.ai/typesafe/jev-1.14)
advertises text+image input and decisions output. Parent verification of its
[endpoint metadata](https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints)
resolved `typesafe/jev-1.14-20261014`; the bundled adapter validates that exact
response identity. Request `--model typesafe/jev-1.14`, not the resolved ID.
Account/service readiness still needs checking at execution time.

Direct TypeSafe uses `jev-1.14.0` or `jev-preview` for Box questions, according to
the [Box contract](https://docs.typesafe.ai/primitives/box). Its general alias
documentation still names 1.13 in the supplied 2026-10-15 source snapshot;
do not equate those aliases with the pinned OpenRouter route. This CLI has no
direct TypeSafe provider. The adapter's historical 1.13 text-only restriction
does not establish an upstream image limitation. Tree control still uses
accessibility content, not screenshots.

OpenRouter receives goals, approved literals, and accessibility content.
A remote Winnow base also sends those off-host. Loopback may be a remote tunnel;
establish the actual destination within existing authorization before a request.
Plugin activation, a probability, and a successful health check grant no data
transfer permission.

OpenRouter credentials: `OPENROUTER_API_KEY_FILE` or `OPENROUTER_API_KEY`.
Winnow credentials, when required: `WINNOW_API_KEY_FILE` or `WINNOW_API_KEY`.
Explicit `--api-key-file` takes precedence, then the provider key-file variable,
then its key variable. Never put a credential literal in an argument, URL, trace,
or report. The CLI has no `--api-key` flag. Do not dump environment values or HTTP
bodies while troubleshooting.

Provider rejection, malformed answers, unsupported capability, and unavailable
services are failures to report. Do not replace them with a synthetic success.
