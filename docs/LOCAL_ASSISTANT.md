# Optional local AI drafts

FieldForge can ask an **installed local Ollama text model** to draft a short answer
from matching articles in your knowledge library. This is an optional desktop/CLI
integration. No model or reviewed survival corpus is bundled, and it does not yet
provide an Android or iOS inference runtime.

## Prepare your computer

1. Install [Ollama](https://ollama.com/) separately and install a local text model
   suitable for your available memory. Model installation requires a separate
   download or transfer before going offline. FieldForge never pulls a model.
2. Disable Ollama's cloud features. Set `OLLAMA_NO_CLOUD=1` **for the Ollama server
   process**, then restart Ollama. Alternatively, set `disable_ollama_cloud` to
   `true` in Ollama's `~/.ollama/server.json` configuration. See the official
   [configuration instructions](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).
   Setting the environment variable only for FieldForge does not change an
   already running Ollama server.
3. Use an Ollama version whose `GET /api/status` reports
   `{"cloud":{"disabled":true}}`. FieldForge refuses to send questions when this
   check fails, including on older servers without the endpoint. The upstream
   status API is experimental; incompatible versions fail closed.
4. Import articles you are entitled to use into the local library. The quality
   and completeness of those articles determine what evidence is available.

For example, when starting the server manually on Linux/macOS, quit any existing
Ollama server first, then run:

```bash
OLLAMA_NO_CLOUD=1 ollama serve
```

On Windows PowerShell, the equivalent in the server's terminal is:

```powershell
$env:OLLAMA_NO_CLOUD = "1"
ollama serve
```

For a background service or the macOS/Windows app, follow Ollama's platform-specific
environment-variable instructions in its FAQ and restart that service or app.

## Desktop

Open **Knowledge Library → Find passages**. **Find passages** remains a model-free
search; opening the window does not contact Ollama.

To request a draft:

1. Click **Load models**. Select a local model from the list. If your local Ollama
   uses a different port, enter it first (default `11434`).
2. Enter your question and click **Draft answer**.
3. Read the **AI draft** and its notices. Open **Source passages** to inspect each
   cited excerpt, source metadata, safety label, and full article.

Opening a draft's full source hides the draft window while you read. Choose
**Find passages** again to return to the same draft without regenerating it.

The window remains responsive while working. **Cancel** or closing the window
interrupts an active HTTP request. Cancellation stops FieldForge waiting and
discards the result; it does not promise immediate GPU release by Ollama. Changing
the question and searching again clears the old draft. Drafts are not saved to the
database. Ordinary passage search still works if Ollama is unavailable.

## Command line

List installed models, then use the exact name returned by that command:

```bash
fieldforge local-models
fieldforge --database fieldforge.db ask "How should I organize my reference books?" --model YOUR_LOCAL_MODEL_NAME
```

Equivalent portable commands:

```bash
python -m fieldforge.knowledge models
python -m fieldforge.knowledge --database fieldforge.db ask "reference books" --model YOUR_LOCAL_MODEL_NAME
```

Both support `--port`; `ask` supports `--timeout` in seconds (default 120, maximum
300). Model discovery has a maximum ten-second deadline. JSON output includes
`status`, `answer`, `model`, `warnings`, recognized `citations`, and `evidence` with
stable labels within that answer (`S1`, `S2`, …), verbatim excerpts, article body
checksums, offsets, and author-supplied provenance. No matching excerpts produces
`status: "no_evidence"` without contacting Ollama. Setup/transport failures exit
with an error instead of silently switching providers.

## What is sent, and what is checked

- FieldForge uses direct HTTP to **127.0.0.1 only**. It accepts a port, not a remote
  URL, ignores proxy environment variables, and does not follow HTTP redirects.
- Before every draft it checks cloud-disabled status, the installed-model list,
  and model details. Remote model aliases and models without text-completion
  capability are rejected. The server must be a trusted local Ollama instance;
  these checks are not an OS network sandbox for other software.
- Only the question and up to four matching article excerpts (700 characters
  each), their labels, titles, review dates, and safety labels enter the prompt.
  Private notes, bookmarks, inventory, and household records are excluded. Text
  you put in the question or article body is still sent to your local model.
- Search checks stored article body checksums. Generated claims are **not fact
  checked**. A valid `[S1]` means the label exists, not that the source supports
  the claim. Missing and unknown labels produce visible notices. Inspect the
  full article before relying on a draft, especially for high-stakes decisions.
- Article text is framed as reference data in the prompt, but a model can still
  follow misleading text or invent facts. There are no executable model tools,
  web search, cloud fallback, telemetry, or automatic writes from model output.
- Generation uses an 8192-token context and a 768-token output budget, with a
  2 MiB HTTP-response ceiling and a 16,000-character answer ceiling. Output-limit
  termination is marked potentially incomplete. Models differ in memory needs,
  latency, instruction following and citation quality. Retrieved passages may
  omit relevant context; lexical search can miss synonyms.
- `keep_alive: 0` asks Ollama to unload after the request. FieldForge keeps no
  conversation history. Ollama's own logging and memory behavior are separate.

## Verification and current limits

Automated tests use a local HTTP fixture to exercise the actual adapter, including
cloud refusal, redirects, malformed responses, private-note exclusion, citation
notices, timeout/cancellation, CLI output and GUI source navigation. They do not
measure real model answer quality. A real downloaded-model inference run and
hardware-specific performance validation remain necessary before a release.

Upstream interface references:
[chat](https://docs.ollama.com/api/chat),
[model list](https://docs.ollama.com/api/tags),
[response types and cloud status](https://github.com/ollama/ollama/blob/main/api/types.go),
[experimental status client](https://github.com/ollama/ollama/blob/main/api/client.go).
