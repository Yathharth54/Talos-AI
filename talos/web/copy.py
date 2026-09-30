"""Every user-facing string the web layer sends (overview spec §4.5).

The copy is fixed and matches the approved Workbench demo word for word
(`docs/superpowers/specs/reference/workbench-demo/index.html`). Templates
use `str.format` fields; the literal text around each field appears
verbatim in the reference file, and `tests/web/test_copy.py` checks it.

Numbers that the demo shows as literals come from settings instead:
`{max}` is `TALOS_FORGE_MAX_RETRIES`, `{timeout}` is
`TALOS_SUBPROCESS_TIMEOUT`, `{prune}` is the vault's auto-prune threshold.

`NEW_COPY` holds the few strings the demo never needed (multi-sub-task
plans, a forge that runs out of attempts). They are listed in the
frontend spec §7 and are exempt from the reference check.
"""

from __future__ import annotations

# ---- captions (under the graph strip) ---------------------------------------

CAPTION_PLANNING = "The Planner is splitting your request into sub-tasks and checking the vault."
CAPTION_PLAN_FORGE = "1 sub-task. Nothing in the vault matches, so it needs a new tool."
CAPTION_PLAN_FORGE_WEATHER = (
    "1 sub-task. Nothing in the vault fetches weather, so it needs a new tool."
)
CAPTION_PLAN_VAULT_KEYWORDS = (
    'The Planner matched <span class="mono">{tool}</span> on the keywords {keywords}.'
    " Nothing will be written or tested this time."
)
CAPTION_PLAN_VAULT = 'The Planner matched <span class="mono">{tool}</span> in the vault.'
CAPTION_PLAN_PRIMITIVE = "1 sub-task, a built-in primitive. Nothing needs forging."
CAPTION_PLAN_CHAT = (
    "The Planner returned an empty plan. There's nothing to run, so Talos answers directly."
)
CAPTION_PLAN_UNKNOWN = "This demo only replays a few scripted runs, so the Planner stops here."
CAPTION_FORGER_FIRST = (
    'The Forger is writing <span class="mono">{tool}</span> and its tests in one structured call.'
)
CAPTION_FORGER_RETRY = (
    '<span class="gold">Attempt {n} of {max}.</span>'
    " The failing test and its traceback went back to the Forger."
)
CAPTION_TESTER = (
    '<span class="gold">Attempt {n} of {max}.</span>'
    " Running {k} tests in a subprocess, {timeout}-second limit."
)
CAPTION_SMOKE = "Smoke test: the tool runs once on a real input before it can be saved."
CAPTION_HUMAN_SKIP = "No API key needed, so Human check passed straight through."
CAPTION_HUMAN_KEY_SET = (
    '<span class="mono">{env}</span> is already set, so Human check passed straight through.'
)
CAPTION_HUMAN_WAIT = (
    'Human check paused the graph. <span class="mono">{tool}</span> needs'
    ' <span class="mono">{env}</span>.'
)
CAPTION_HUMAN_SAVED = 'Saved <span class="mono">{env}</span> to .env. Talos won\'t ask again.'
CAPTION_HUMAN_SKIPPED = (
    "You skipped the key. The tool is still saved, but it will fail until the key is set."
)
CAPTION_LEARN = "Learn is writing the .py file and its manifest entry."
CAPTION_EXECUTOR = "The Executor is reading your message and filling in the arguments."
CAPTION_EXECUTOR_SHORT = "The Executor is filling in the arguments."
CAPTION_EXEC_PAUSED = (
    'The Executor paused. <span class="mono">{tool}</span> runs code on your machine,'
    " so it asks first."
)
CAPTION_EXEC_AUTO = 'Ran without asking, because "Ask before running code" is off in Settings.'
CAPTION_DECLINED = "Nothing ran. The sub-task is recorded as declined."
CAPTION_DONE_FORGED = (
    "Done in {attempts} attempts. No API key was needed, so Human check passed straight through."
)
CAPTION_DONE_VAULT = "Done from the vault. The forge sub-graph never ran."
CAPTION_DONE_PRIMITIVE = "Done. Primitives go straight to the Executor, so nothing was forged."
CAPTION_DONE_WEATHER = "Done. In Talos the Executor would call OpenWeatherMap here with your key."
CAPTION_FAILED = "The run still finished. Talos explained the failure instead of guessing a result."
CAPTION_FAILED_NO_KEY = "The tool ran without its key and raised an error."
CAPTION_STOPPED = "You stopped this run. Nothing was saved to the vault."

# ---- run log lines: (label, text) ---------------------------------------------

LOG_PLAN_FORGE = ("plan", "1 sub-task, needs a new tool")
LOG_PLAN_VAULT = ("plan", "1 sub-task, in the vault")
LOG_PLAN_PRIMITIVE = ("plan", "1 sub-task, primitive")
LOG_PLAN_CHAT = ("plan", "no sub-tasks, answering directly")
LOG_PLAN_UNKNOWN = ("plan", "not in this demo")
LOG_VAULT_MISS = ("vault", "no match")
LOG_VAULT_HIT = ("vault", "{tool}")
LOG_FORGE_FIRST = ("forge", "{tool}()")
LOG_FORGE_RETRY = ("forge", "attempt {n}")
LOG_TEST_RUNNING = ("test", "running")
LOG_TEST_RETRYING = ("test", "{passed} of {total} passed, retrying")
LOG_TEST_PASSED = ("test", "{total} of {total} passed")
LOG_SMOKE = ("smoke", "{result}")
LOG_CHECK_KEY_SET = ("check", "key already set")
LOG_CHECK_WAITING = ("check", "waiting for a key")
LOG_CHECK_SAVED = ("check", "key saved to .env")
LOG_CHECK_SKIPPED = ("check", "skipped by you")
LOG_LEARN = ("learn", "saved to the vault")
LOG_EXEC_DONE = ("execute", "done")
LOG_EXEC_DONE_WEATHER = ("execute", "done (demo stops before the API)")
LOG_EXEC_FAILED = ("execute", "failed, {error_type}")
LOG_EXEC_PAUSED = ("execute", "paused for approval")
LOG_EXEC_RUNNING = ("execute", "running")
LOG_EXEC_DECLINED = ("execute", "declined by you")
LOG_VAULT_REMOVED = ("vault", "removed after {prune} failures in a row")
LOG_VAULT_STREAK = ("vault", "{streak} failure in a row")
LOG_STOP = ("stop", "stopped by you")

# ---- run-log status line (log.status) -------------------------------------------

STATUS_FORGING = "Forging"
STATUS_NONE_FORGED = "0 tools forged"
STATUS_ONE_FORGED = "1 tool forged"
STATUS_STEP_FAILED = "1 step failed"
STATUS_WAITING = "Waiting for you"
STATUS_NOT_RUN = "Not run"
STATUS_NOTHING_RAN = "Nothing ran"
STATUS_STOPPED = "Stopped"

# ---- "working on it" status next to the orbit (talos.status) ---------------------

TALOS_PLANNING = "Planning"
TALOS_WRITING = "Writing {tool}"
TALOS_RETRYING = "The first attempt failed a test. Trying again"
TALOS_RUNNING = "Running {tool}"
TALOS_FOUND = "Found {tool} in the vault"
TALOS_APPROVE = "Waiting for you to approve the code"
TALOS_NEEDS_KEY = "The tool is written and tested. It needs an API key before it can run"

# ---- strip labels -----------------------------------------------------------------

LABEL_FORGE = "Sub-task {i} of {n}, needs a new tool"
LABEL_VAULT = "Sub-task {i} of {n}, found in the vault"
LABEL_PRIMITIVE = "Sub-task {i} of {n}, built-in primitive"
LABEL_CHAT = "Conversational"
LABEL_UNKNOWN = "Scripted demo"
LABEL_EXEC_WAITING = "Executor, waiting for you"
LABEL_EXEC_DECLINED = "Executor, declined"
LABEL_EXEC_FAILED = "Executor failed"
LABEL_HUMAN_SKIPPED = "Human check, skipped"
LABEL_STOPPED_SUFFIX = ", stopped"

# ---- forge details ------------------------------------------------------------------

NOTE_CHANGED_LINE = "Line {line} is new in attempt {n}."
DETAIL_TESTS_PASSED = "{total} of {total} tests passed"
ARGS_CAPTION = "Filled in by the Executor"
ARGS_CAPTION_CODE = "Written by the Executor"
ARGS_CAPTION_NONE = "Takes no arguments"

# ---- vault banner second line (vault.saved.sub) -----------------------------------------

SAVED_SUB = "Next time a request needs {what}, Talos skips forging and goes straight to Execute."
SAVED_SUB_KEY = "Next time you ask about the weather, Talos reuses it. It reads the key from .env."

# ---- chips and run summaries --------------------------------------------------------------

CHIP_FORGED = "Forged {tool}"
CHIP_REUSED = "Reused {tool} from the vault"
CHIP_FAILED = "{tool} raised a {error_type}"

SUMMARY_FORGED = "1 tool forged, {attempts} attempts"
SUMMARY_FORGED_KEY = "1 tool forged, key saved"
SUMMARY_FORGED_NO_KEY = "1 tool forged, failed without a key"
SUMMARY_NO_KEY = "Failed without a key"
SUMMARY_REUSED = "0 tools forged"
SUMMARY_FAILED_STREAK = "Failed, {streak} failure in a row"
SUMMARY_FAILED_PRUNED = "Failed, removed from the vault"
SUMMARY_FAILED = "Failed"
SUMMARY_PRIMITIVE = "Built-in"
SUMMARY_PRIMITIVE_APPROVED = "Built-in, approved"
SUMMARY_DECLINED = "Declined, nothing ran"
SUMMARY_CHAT = "Answered directly"
SUMMARY_UNKNOWN = "Not in this demo"
SUMMARY_STOPPED = "Stopped"

STOP_NOTE = "Stopped. Ask again whenever you're ready."

# ---- scripted answers (fake graph only; html fields must be escaped by the caller) --------

ANSWER_ENCRYPTED = '"{text}" encrypted with a shift of {shift} is <span class="mono">{out}</span>.'
ANSWER_DECRYPTED = 'It decrypts to <span class="mono">{out}</span>.'
NOTE_ENCRYPT_TOO = 'The same tool decrypts too. Ask with "decrypt" and the same shift.'
NOTE_DECRYPT_TOO = 'The same tool encrypts too. Ask with "encrypt" and the same shift.'
ANSWER_CAESAR_FAILED = (
    'I couldn\'t {mode} that. <span class="mono">caesar_cipher</span> needs the shift as a'
    ' number, and it was given the word "{word}".'
)
NOTE_RETRY_DIGIT = 'Ask again with "shift {digit}" and it should work.'
NOTE_RETRY_NUMBER = "Ask again with the shift as a number."
ANSWER_DECLINED = "I didn't run the code, so I don't have its output."
NOTE_DECLINED = "Approve it next time, or turn off the prompt in Settings."
ANSWER_PYTHON = 'The code prints <span class="mono">{out}</span>.'
ANSWER_PYTHON_UNSUPPORTED = (
    'This demo can only run simple <span class="mono">print()</span> calls,'
    " so there's no output to show."
)
RESULT_PYTHON_UNSUPPORTED = "The demo only runs simple print() calls."
ANSWER_WEATHER_NO_KEY = (
    'I couldn\'t get the temperature. <span class="mono">{tool}</span> needs'
    ' <span class="mono">{env}</span>, and it isn\'t set.'
)
NOTE_WEATHER_NO_KEY = "Ask again and paste the key when Human check asks for it."
ANSWER_WEATHER = (
    "The tool is ready and your key is saved. This demo can't reach the internet,"
    " so it stops before calling OpenWeatherMap."
)
NOTE_WEATHER = "In Talos, you'd get the current temperature in {city} here."
RESULT_WEATHER = "Not called in this demo"
ANSWER_CHAT = (
    "I split your request into steps, then use a built-in tool, reuse one from my vault,"
    " or write and test a new Python tool for whatever's missing."
    " The vault holds {count} tools right now."
)
NOTE_CHAT = "Try asking me to build a Caesar cipher."
ANSWER_UNKNOWN = (
    "This demo can't plan that one. It replays a few scripted runs over the real vault."
    " Try one of these:"
)

# ---- Settings page key descriptions ---------------------------------------------------------

KEY_DESCRIPTIONS = {
    "OPENROUTER_API_KEY": "Required. Every model call goes through OpenRouter.",
    "TAVILY_API_KEY": "Needed for web search.",
    "JINA_API_KEY": "Optional. Raises web-reading limits.",
    "LANGSMITH_API_KEY": "Optional. Traces every node in LangSmith.",
}
KEY_SAVED_BY_HUMAN_CHECK = "Saved by Human check"

# ---- strings the demo never needed (frontend spec §7) ---------------------------------------

NEW_COPY = {
    "CAPTION_PLAN_MULTI": "{n} sub-tasks. Talos works through them in order.",
    "LOG_PLAN_MULTI": "{n} sub-tasks",
    "CAPTION_FORGE_GAVE_UP": "The Forger used all {max} attempts. Nothing was saved to the vault.",
    "LOG_FORGE_GAVE_UP": "gave up after {n} attempts",
    "LOG_TEST_FAILED": "{passed} of {total} passed",
    "LOG_SMOKE_FAILED": "failed",
    "TALOS_RETRYING_N": "Attempt {n} failed a test. Trying again",
    "SUMMARY_FORGED_MANY": "{k} tools forged",
    "SUMMARY_FORGED_ONE": "1 tool forged, 1 attempt",
    "CAPTION_DONE_FORGED_ONE": (
        "Done in 1 attempt. No API key was needed, so Human check passed straight through."
    ),
    "CAPTION_DONE_FORGED_KEY": "Done in {attempts}. Your key is saved to .env.",
}


def new(key: str, **fields: object) -> str:
    """Format one of the `NEW_COPY` strings."""
    return NEW_COPY[key].format(**fields)


def join_words(words: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`: the demo's keyword list style."""
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]
