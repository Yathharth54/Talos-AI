# Talos AI — End-to-End Test Suite

> **Purpose**: 65 queries that exercise every component, edge, and interaction pattern in Talos.
> Run them **in order** — some later queries rely on tools forged by earlier ones to test vault reuse.
> Each query is independently valid (no shared state assumptions beyond the vault).

---

## How to read each entry

| Field | Meaning |
|---|---|
| **Query** | Exact string to feed into the REPL |
| **Tests** | What this query is specifically validating |
| **Components** | Which pipeline stages should activate |
| **Pass criteria** | Observable conditions that mean "this worked" |
| **Notes** | Hints for debugging or context |

Component shorthand: `PL` = Planner, `EX` = Executor, `FG` = Forger, `TS` = Tester, `SK` = Skill Manager (search/register), `RS` = Researcher (Tavily/Jina), `HI` = human_input interrupt, `OR` = Orchestrator routing/combining.

---

## Category 1 — Primitive Isolation

These test raw primitives in isolation. If these fail, nothing downstream will work.

---

### Q01 · web_search primitive
- **Query**: `What is the current population of Iceland?`
- **Tests**: Tavily web_search returns results, Planner correctly identifies this as a single primitive call
- **Components**: `PL → EX(web_search)`
- **Pass criteria**: Response contains a recent population figure (~380k–400k range). No forge triggered. Trace shows a single Tavily call.
- **Notes**: The simplest possible web query. If this fails, check Tavily API key in .env.

### Q02 · web_read primitive
- **Query**: `Read the contents of https://httpbin.org/html and tell me what the page says.`
- **Tests**: Jina Reader fetches a URL and returns content, Planner routes to web_read
- **Components**: `PL → EX(web_read)`
- **Pass criteria**: Response mentions Herman Melville / Moby Dick (that's what httpbin.org/html serves). No forge triggered.
- **Notes**: httpbin.org/html is a stable test endpoint. If Jina fails, verify r.jina.ai prefix is being used.

### Q03 · python_exec primitive
- **Query**: `Run this Python code and give me the output: print(sum(range(1, 101)))`
- **Tests**: subprocess execution, stdout capture, Planner recognizes explicit code-run request
- **Components**: `PL → EX(python_exec)`
- **Pass criteria**: Response contains `5050`. Execution completes in well under the 10s timeout.
- **Notes**: Classic Gauss sum. Tests the most basic subprocess path.

### Q04 · shell_exec primitive
- **Query**: `What operating system is this machine running? Use a shell command to find out.`
- **Tests**: Shell command execution (uname or similar), Planner routes to shell_exec
- **Components**: `PL → EX(shell_exec)`
- **Pass criteria**: Response contains OS info (Linux/macOS/etc.). Executed via shell, not python_exec.
- **Notes**: Tests that shell_exec is treated as distinct from python_exec.

### Q05 · file_write + file_read primitives
- **Query**: `Write the text "Talos test marker" to a file called /tmp/talos_test.txt, then read it back and confirm the contents.`
- **Tests**: File I/O round-trip, Planner generates a 2-step sequential plan (write then read)
- **Components**: `PL → EX(file_write) → EX(file_read)`
- **Pass criteria**: File exists at /tmp/talos_test.txt. Response confirms contents match. Both primitives show in trace.
- **Notes**: First multi-step plan in the suite — tests basic Planner sequencing.

---

## Category 2 — Single-Tool Forge (Pure Computation)

Each query requires the Forger to create exactly one pure Python function. No I/O, no API calls. Increasing complexity.

---

### Q06 · Trivial forge — Fibonacci
- **Query**: `Build me a tool that returns the Nth Fibonacci number. Then use it to get the 20th Fibonacci number.`
- **Tests**: Forge→test→register pipeline for the simplest possible case, then immediate execution
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX(forged tool)`
- **Pass criteria**: Tool registered in manifest.json. Returns `6765` for N=20. vault/tools/ contains the .py file.
- **Notes**: If this fails the forge loop is broken. Check Forger's prompt, Tester subprocess, and manifest write.

### Q07 · String manipulation forge
- **Query**: `Create a tool that takes a string and returns it in alternating case (e.g., "hello" → "hElLo"). Test it on "talos artificial intelligence".`
- **Tests**: Forger handles string processing, Tester validates edge cases
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Output is `tAlOs ArTiFiCiAl InTeLlIgEnCe` (or equivalent valid alternating pattern). Tool persisted.
- **Notes**: Tests that Tester generates meaningful string test cases, not just "does it not crash."

### Q08 · Mathematical forge — prime factorization
- **Query**: `Forge a tool that returns the prime factorization of any positive integer. Use it on 84942.`
- **Tests**: Non-trivial algorithm forging, correct mathematical output
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `[2, 3, 3, 17, 277]` (i.e., 2 × 3² × 17 × 277 = 84942). Tool persisted.
- **Notes**: Tests algorithmic correctness — Tester should catch bugs in trial division or similar approaches.

### Q09 · Data structure forge — frequency counter
- **Query**: `Create a tool that takes a list of strings and returns a dictionary mapping each string to its frequency, sorted by frequency descending. Run it on: ["apple", "banana", "apple", "cherry", "banana", "apple"]`
- **Tests**: Dict return type, sorting logic, Forger handles collections
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `{"apple": 3, "banana": 2, "cherry": 1}`. Tool persisted.
- **Notes**: Tests that Forger produces properly typed functions with dict returns.

### Q10 · Algorithmic forge — Levenshtein distance
- **Query**: `Forge a tool that computes the Levenshtein edit distance between two strings. What's the distance between "kitten" and "sitting"?`
- **Tests**: Dynamic programming algorithm, Forger handles non-trivial CS concept
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `3`. Tool persisted. Tester should validate known pairs.
- **Notes**: Classic DP problem. If Forger struggles, it's a signal the system prompt needs better algorithm guidance.

### Q11 · Encoding forge — Caesar cipher
- **Query**: `Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.`
- **Tests**: Tool with multiple modes (encrypt/decrypt), parameter handling
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `AHSVZ HNLUA`. Tester should verify round-trip (encrypt then decrypt = original).
- **Notes**: Tests that Forger can create tools with mode parameters, not just single-purpose functions.

---

## Category 3 — Vault Reuse / Skill Memory

These depend on tools forged in Category 2. They validate that the Skill Manager finds and reuses existing tools instead of re-forging.

---

### Q12 · Reuse Fibonacci tool
- **Query**: `What is the 30th Fibonacci number?`
- **Tests**: SK search matches the Fibonacci tool from Q06, Planner chooses vault over forge
- **Components**: `PL → SK(search, hit) → EX(vault tool)`
- **Pass criteria**: Returns `832040`. **No Forger invocation in trace.** Skill Manager search logged a match.
- **Notes**: Critical test — if this re-forges, the skill accumulation story is broken. Check SK search keywords.

### Q13 · Reuse Levenshtein tool
- **Query**: `How similar are the words "algorithm" and "altruistic"? Use edit distance.`
- **Tests**: SK search matches Levenshtein tool from Q10, Planner recognizes "edit distance" maps to existing tool
- **Components**: `PL → SK(search, hit) → EX(vault tool)`
- **Pass criteria**: Returns `6`. No Forger invocation. SK search logged.
- **Notes**: Tests keyword matching — "edit distance" should match even though the original query said "Levenshtein."

### Q14 · Reuse Caesar cipher tool
- **Query**: `Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"`
- **Tests**: SK finds Caesar tool from Q11, Planner routes to decrypt mode
- **Components**: `PL → SK(search, hit) → EX(vault tool)`
- **Pass criteria**: Returns `TALOS AGENT`. No forge. Correct mode selection (decrypt, not encrypt).
- **Notes**: Tests that the executor correctly passes the "decrypt" mode parameter to a previously forged tool.

### Q15 · Near-miss vault search — should forge, not reuse
- **Query**: `Build a tool that computes the Hamming distance between two strings of equal length. What's the Hamming distance between "karolin" and "kathrin"?`
- **Tests**: SK search finds Levenshtein (related but wrong), Planner correctly decides to forge a new tool
- **Components**: `PL → SK(search, near-miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `3`. A **new** tool is forged (not reusing Levenshtein). Both tools exist in manifest afterward.
- **Notes**: Critical discrimination test — "string distance" could falsely match Levenshtein. Tests SK search precision.

---

## Category 4 — Research-Then-Act

Queries where the agent must first gather information via Researcher before acting.

---

### Q16 · Simple web search + synthesis
- **Query**: `Who won the most recent FIFA World Cup and what was the final score?`
- **Tests**: Tavily search, result extraction, Planner routes to research path
- **Components**: `PL → RS(web_search) → OR(synthesize)`
- **Pass criteria**: Correct winner and score. Source should be from web_search results.
- **Notes**: Tests basic Researcher→Orchestrator flow for factual queries.

### Q17 · Web read + summarize
- **Query**: `Read the Python PEP 8 style guide from https://peps.python.org/pep-0008/ and give me the 5 most important rules.`
- **Tests**: Jina Reader on a real-world long page, Planner decomposes into read+summarize
- **Components**: `PL → RS(web_read) → OR(summarize)`
- **Pass criteria**: Response lists 5 genuine PEP 8 rules (indentation, naming, imports, etc.). Content clearly comes from the URL, not from LLM general knowledge.
- **Notes**: Tests Jina on a longer page. If Jina truncates, response quality will suffer — good stress test.

### Q18 · Research for a factual comparison
- **Query**: `Compare the current GitHub star counts of LangChain and LlamaIndex. Which has more?`
- **Tests**: Multiple Tavily searches (one per project), comparison synthesis
- **Components**: `PL → RS(web_search ×2) → OR(compare + respond)`
- **Pass criteria**: Response includes two numbers and a comparison. Numbers are plausible (both >30k). Trace shows 2 separate searches.
- **Notes**: Tests Planner's ability to parallelize independent research sub-tasks (or sequence them).

### Q19 · Research with URL extraction
- **Query**: `Find the official LangGraph documentation URL and read their quickstart guide. What are the 3 core concepts they introduce first?`
- **Tests**: Tavily search → URL discovery → Jina read → content extraction. Multi-hop research.
- **Components**: `PL → RS(web_search) → RS(web_read) → OR(extract + respond)`
- **Pass criteria**: Correct URL found. 3 concepts listed match actual LangGraph docs (StateGraph, nodes, edges or similar).
- **Notes**: Tests the Researcher's ability to chain search→read. If it hallucinates the URL, that's a Researcher bug.

### Q20 · Research with current data
- **Query**: `What is today's date and what is the top trending repository on GitHub right now?`
- **Tests**: Time-sensitive query handling, Tavily freshness
- **Components**: `PL → RS(web_search) → OR(respond)`
- **Pass criteria**: Correct date. A real GitHub repo that's plausibly trending. Not stale/hallucinated data.
- **Notes**: Tests freshness. If Tavily returns old results, check search parameters.

---

## Category 5 — Research-Informed Forging

The Forger needs Researcher context to write correct code.

---

### Q21 · Forge with domain research — color conversion
- **Query**: `Build a tool that converts HEX color codes to RGB tuples. Convert #1A2B3C.`
- **Tests**: Forger may look up hex-to-RGB math (or know it), forge + test + execute
- **Components**: `PL → SK(search, miss) → RS(optional) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `(26, 43, 60)`. Tool persisted. Code uses correct bit-shifting or int parsing.
- **Notes**: Forger might not need Researcher for this — that's fine. Tests that the pipeline doesn't force unnecessary research.

### Q22 · Forge with API format research — Unix timestamp converter
- **Query**: `Create a tool that converts a Unix timestamp to a human-readable UTC datetime string. Convert 1700000000.`
- **Tests**: Forger handles datetime formatting, may research format conventions
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `2023-11-14 22:13:20` (or equivalent UTC representation). Tool persisted.
- **Notes**: Tests stdlib usage (datetime module). Tester should validate known timestamps.

### Q23 · Forge with formula research — haversine distance
- **Query**: `Forge a tool that calculates the great-circle distance between two lat/long coordinates using the Haversine formula. Distance from Mumbai (19.076, 72.8777) to Tokyo (35.6762, 139.6503)?`
- **Tests**: Forger researches Haversine formula, implements math correctly
- **Components**: `PL → SK(search, miss) → RS(web_search) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns approximately 6,740 km (±50 km). Tool persisted.
- **Notes**: Forger almost certainly needs the formula. Tests RS→FG handoff. Good test for Tester validating float precision.

### Q24 · Forge with encoding research — base64
- **Query**: `Build a tool that base64-encodes and decodes strings. Encode "Talos forges tools at runtime" and then decode the result to verify.`
- **Tests**: Round-trip verification, Forger handles encoding patterns
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Encode produces `VGFsb3MgZm9yZ2VzIHRvb2xzIGF0IHJ1bnRpbWU=`. Decode returns original string. Tool persisted.
- **Notes**: Tests round-trip correctness. Tester should specifically verify encode→decode identity.

### Q25 · Forge with statistical formula — standard deviation
- **Query**: `Create a tool that computes the population standard deviation of a list of numbers. No numpy allowed. Compute it for [2, 4, 4, 4, 5, 5, 7, 9].`
- **Tests**: Pure Python math implementation, constraint following (no numpy)
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `2.0`. Forged code does not import numpy. Tool persisted.
- **Notes**: Tests constraint propagation — the "no numpy" instruction must reach the Forger. Classic textbook example (μ=5, σ=2).

---

## Category 6 — Multi-Step Sequential Plans

Queries requiring 2–4 sub-tasks with data flowing between steps.

---

### Q26 · Search → extract → save (3 steps)
- **Query**: `Search the web for the latest Python release version, then write that version number to a file called /tmp/python_version.txt.`
- **Tests**: Planner decomposes into search→extract→file_write, data passes between steps
- **Components**: `PL → RS(web_search) → EX(file_write) → OR(confirm)`
- **Pass criteria**: File exists with a valid Python version string (e.g., "3.13.x"). Search trace visible.
- **Notes**: Tests state passing — the version string from research must flow into the file_write step.

### Q27 · Read → transform → write (3 steps)
- **Query**: `Read the file /tmp/talos_test.txt (it should say "Talos test marker"), convert the contents to uppercase, and write the result to /tmp/talos_upper.txt.`
- **Tests**: File_read → string transform → file_write pipeline, cross-step data flow
- **Components**: `PL → EX(file_read) → EX(python_exec or vault tool) → EX(file_write)`
- **Pass criteria**: /tmp/talos_upper.txt contains `TALOS TEST MARKER`. All 3 steps visible in trace.
- **Notes**: Depends on Q05 having written the original file. Tests read→transform→write chain.

### Q28 · Research → forge → execute → save (4 steps)
- **Query**: `Look up the current Bitcoin price in USD, then forge a tool that converts USD to INR at a rate of 83.5, convert the BTC price, and save the INR amount to /tmp/btc_inr.txt.`
- **Tests**: Maximum pipeline depth — research, forge, execute, file I/O all in one query
- **Components**: `PL → RS(web_search) → FG → TS → SK(register) → EX(forged tool) → EX(file_write)`
- **Pass criteria**: File contains a plausible INR value (BTC price × 83.5). All 4 stages visible in trace.
- **Notes**: The most complex sequential plan so far. Tests Planner's ability to generate a deep dependency chain.

### Q29 · Forge two tools in sequence
- **Query**: `Create a tool that generates a random password of a given length (letters, digits, symbols). Then create a separate tool that scores password strength (weak/medium/strong based on length, character diversity). Generate a 16-char password and score it.`
- **Tests**: Planner creates a plan with TWO forge sub-tasks, then executes both
- **Components**: `PL → FG(tool1) → TS → SK(register) → FG(tool2) → TS → SK(register) → EX(tool1) → EX(tool2)`
- **Pass criteria**: Two new tools in manifest. Password is 16 chars with mixed chars. Score is "strong". Both .py files exist.
- **Notes**: Tests multi-forge plans. Planner must correctly sequence forge→forge→execute→execute.

### Q30 · Fetch → parse → compute → respond (4 steps)
- **Query**: `Read the page at https://jsonplaceholder.typicode.com/users and tell me how many users have email addresses ending in .biz.`
- **Tests**: Web_read on a JSON endpoint, parsing, counting, synthesizing
- **Components**: `PL → RS(web_read) → EX(python_exec or forge) → OR(respond)`
- **Pass criteria**: Returns the correct count from the JSONPlaceholder data. Content clearly parsed from the API response.
- **Notes**: Tests handling of JSON content from Jina Reader. The answer should be consistent across runs (static API).

---

## Category 7 — Mixed Pipeline (Forge + Primitive + Vault)

Real-world-style queries combining all pipeline types.

---

### Q31 · Vault tool + primitive combo
- **Query**: `What's the Fibonacci number at position 15, and write that number to /tmp/fib15.txt?`
- **Tests**: SK finds Fibonacci tool from vault (Q06), then primitive file_write
- **Components**: `PL → SK(search, hit) → EX(vault tool) → EX(file_write)`
- **Pass criteria**: File contains `610`. No forge triggered. Both execution steps logged.
- **Notes**: Tests mixed vault+primitive in a single plan.

### Q32 · Research + vault tool combo
- **Query**: `Find the distance in km between the Eiffel Tower coordinates (48.8584, 2.2945) and the Statue of Liberty coordinates (40.6892, -74.0445) using the haversine tool.`
- **Tests**: Planner recognizes haversine tool exists in vault (Q23), routes correctly
- **Components**: `PL → SK(search, hit) → EX(vault tool)`
- **Pass criteria**: Returns approximately 5,837 km (±50 km). Haversine tool reused, no forge.
- **Notes**: Tests vault reuse for a tool with specific parameters (lat/long pairs).

### Q33 · Research + forge + vault in one plan
- **Query**: `Search the web for the top 5 most popular programming languages in 2025, forge a tool that takes a ranked list and formats it as a numbered markdown list, then apply the tool to the results.`
- **Tests**: Three pipeline types in one query — RS, FG, and EX together
- **Components**: `PL → RS(web_search) → FG → TS → SK(register) → EX(forged tool) → OR(respond)`
- **Pass criteria**: Response contains a properly numbered markdown list of 5 real languages. Forge trace shows tool creation. Research trace shows Tavily call.
- **Notes**: The "Talos showcase" query — demonstrates the full pipeline in action.

### Q34 · Vault reuse + new forge combo
- **Query**: `Take the string "Hello World", compute its Caesar cipher with shift 3, then compute the Levenshtein distance between the original and the encrypted version.`
- **Tests**: Two vault tools chained (Caesar from Q11, Levenshtein from Q10), Planner sequences them
- **Components**: `PL → SK(search, hit ×2) → EX(Caesar vault) → EX(Levenshtein vault)`
- **Pass criteria**: Caesar output is `KHOOR ZRUOG`. Levenshtein distance between "Hello World" and "KHOOR ZRUOG" returned (case-sensitive). No forge triggered.
- **Notes**: Tests multi-vault-tool plans. Planner must recognize both tools exist.

---

## Category 8 — Human-in-the-Loop

Queries that trigger the interrupt flow for user input.

---

### Q35 · API key request — Tier 2 service
- **Query**: `Use the OpenWeatherMap API to get the current temperature in Mumbai.`
- **Tests**: Agent discovers it needs an API key, triggers human_input interrupt, handles the key
- **Components**: `PL → RS(web_search to discover API needs) → HI(ask for key) → FG(build API tool) → EX`
- **Pass criteria**: Agent pauses and asks user for OpenWeatherMap API key. After key is provided, it either forges an API tool or explains it needs the key. Interrupt flow works without crashing.
- **Notes**: The exact end state depends on whether the user provides a real key. The test is: does the interrupt trigger cleanly?

### Q36 · Clarification interrupt — ambiguous query
- **Query**: `Convert the data.`
- **Tests**: Agent recognizes query is too vague, uses human_input to ask for clarification
- **Components**: `PL → HI(ask for clarification)`
- **Pass criteria**: Agent asks a clarifying question (what data? convert to what format?). Does NOT hallucinate an interpretation and blindly proceed.
- **Notes**: Tests graceful handling of underspecified queries. The Planner should recognize it can't decompose this.

### Q37 · User preference interrupt — ambiguous choice
- **Query**: `Generate a color palette for a website. I want 5 colors.`
- **Tests**: Agent recognizes it needs user input (what mood/style/brand?) before it can produce a useful result, triggers human_input
- **Components**: `PL → HI(ask for style/mood preference) → FG(palette generator) or EX(python_exec)`
- **Pass criteria**: Agent asks a clarifying question about style, mood, or brand direction before generating colors. Does NOT just spit out random hex codes without context.
- **Notes**: Tests the interrupt for preference gathering, not just API keys or confirmations. The agent should recognize that "5 colors" without context is underspecified.

---

## Category 9 — Failure and Recovery

Deliberately tricky inputs that test error handling, retries, and graceful degradation.

---

### Q38 · Forge retry — buggy first attempt
- **Query**: `Build a tool that validates email addresses using regex. It should handle edge cases like "user+tag@sub.domain.com" and reject "user@@domain" and "@domain.com".`
- **Tests**: Tester catches edge cases the Forger's first attempt might miss, triggers retry loop
- **Components**: `PL → SK(search, miss) → FG → TS(fail?) → FG(retry) → TS(pass) → SK(register) → EX`
- **Pass criteria**: Final tool correctly validates all listed examples. Trace may show 1–3 forge attempts. Tool persisted after passing tests.
- **Notes**: Email regex is notoriously tricky — this specifically stresses the retry loop.

### Q39 · Timeout stress — expensive computation
- **Query**: `Forge a tool that finds all prime numbers up to N. Run it with N = 10,000,000.`
- **Tests**: Subprocess timeout handling, Forger writing efficient code
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Either returns correct count (664,579 primes under 10M) within timeout, OR gracefully reports timeout and suggests a smaller N. No crash, no hang.
- **Notes**: Tests the 10s subprocess timeout. Naive implementation will timeout; efficient sieve won't. Tests whether Forger writes performant code.

### Q40 · Impossible task — graceful refusal
- **Query**: `Forge a tool that accurately predicts stock prices for tomorrow.`
- **Tests**: Agent recognizes this is infeasible, declines gracefully instead of hallucinating a tool
- **Components**: `PL → OR(refuse gracefully)`
- **Pass criteria**: Agent explains why this isn't possible rather than forging a fake predictor. No tool registered.
- **Notes**: Tests judgment — the Planner or Orchestrator should catch this before reaching the Forger.

### Q41 · Missing dependency handling
- **Query**: `Build a tool that uses the 'obscurelib42' package to transform data.`
- **Tests**: Forger produces code importing a non-existent package, Tester catches ImportError, system handles gracefully
- **Components**: `PL → FG → TS(fail - ImportError) → FG(retry without fake dep) → TS → SK(register)`
- **Pass criteria**: Agent either explains the package doesn't exist, or retries with stdlib-only approach. No broken tool registered.
- **Notes**: Tests Tester's ability to catch import failures and Forger's ability to recover.

### Q42 · Malformed input handling
- **Query**: `Use the prime factorization tool on -17.`
- **Tests**: Executor handles invalid input to a vault tool, error propagates cleanly
- **Components**: `PL → SK(search, hit) → EX(vault tool, error)`
- **Pass criteria**: Agent reports that prime factorization is defined for positive integers > 1, not negative numbers. No crash.
- **Notes**: Tests error handling in the Executor when vault tools receive bad input.

### Q43 · Web search with no useful results
- **Query**: `Find the detailed quarterly revenue breakdown for Yathendra's Lemonade Stand Inc. in Q3 2025.`
- **Tests**: Researcher gets no useful results, agent reports inability honestly
- **Components**: `PL → RS(web_search, no results) → OR(report honestly)`
- **Pass criteria**: Agent says it couldn't find this information. Does NOT fabricate financial data. No hallucinated numbers.
- **Notes**: Tests hallucination resistance when Researcher returns nothing useful.

---

## Category 10 — Adversarial and Edge Cases

Stress-test the boundaries of routing, parsing, and interpretation.

---

### Q44 · Empty input
- **Query**: *(empty string)*
- **Tests**: REPL / Orchestrator handles empty input without crashing
- **Components**: `OR(handle gracefully)`
- **Pass criteria**: Agent asks what the user needs or provides a usage hint. No exception, no crash.
- **Notes**: Simplest edge case. Tests input validation at the REPL level.

### Q45 · Extremely long input
- **Query**: `Summarize the following: ` + (repeat "The quick brown fox jumps over the lazy dog. " × 500)
- **Tests**: Token limit handling, Planner doesn't choke on massive input
- **Components**: `PL → OR(summarize)`
- **Pass criteria**: Agent summarizes or notes the repetition. No OOM, no crash, no infinite loop.
- **Notes**: Tests input length handling. May hit context limits — graceful truncation is fine.

### Q46 · Sounds like forge but is a primitive
- **Query**: `Calculate 2 ** 100.`
- **Tests**: Planner correctly routes to python_exec instead of forging a power-calculation tool
- **Components**: `PL → EX(python_exec)`
- **Pass criteria**: Returns `1267650600228229401496703205376`. No forge triggered — this is a one-liner.
- **Notes**: Tests Planner discrimination between "needs a tool" and "just run it."

### Q47 · Sounds like a primitive but needs a forge
- **Query**: `Generate a UUID v4.`
- **Tests**: Planner could route to python_exec (one-liner) OR forge a reusable UUID tool — either is acceptable
- **Components**: `PL → EX(python_exec)` OR `PL → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns a valid UUID v4 (8-4-4-4-12 hex format, version nibble = 4). Either route is fine.
- **Notes**: Ambiguous routing test. Both outcomes are valid — the test is that it works, not which path it takes.

### Q48 · Chained vault reuse — 3 tools
- **Query**: `Encode the string "Test123" in base64, then compute the Levenshtein distance between the original and encoded strings, then check if the distance value is a prime number using factorization.`
- **Tests**: Three vault tools chained in sequence (base64 from Q24, Levenshtein from Q10, prime factorization from Q08)
- **Components**: `PL → SK(search, hit ×3) → EX(base64) → EX(levenshtein) → EX(prime_check) → OR`
- **Pass criteria**: Base64 output is `VGVzdDEyMw==`. Levenshtein distance computed. Factorization applied to the distance. All vault tools reused, no forge.
- **Notes**: Maximum vault chain. Tests Planner's ability to build complex plans entirely from existing tools.

### Q49 · Self-referential query
- **Query**: `How many tools are currently in your skill vault? List them all.`
- **Tests**: Agent queries the Skill Manager directly, meta-awareness of its own capabilities
- **Components**: `PL → SK(list all) → OR(format and respond)`
- **Pass criteria**: Response lists all tools registered by previous queries (Fibonacci, Caesar, Levenshtein, etc.). Count matches manifest.json entries.
- **Notes**: Tests SK's list/enumerate capability and the agent's self-awareness of its tool inventory.

### Q50 · Full showcase — end-to-end stress test
- **Query**: `I want to compare two GitHub repos: langchain-ai/langchain and run-llama/llama_index. Search for their star counts, forge a tool that takes two numbers and computes the percentage difference, apply it to the star counts, then format the result as a one-line summary and save it to /tmp/repo_comparison.txt.`
- **Tests**: Every component in one query — RS, FG, TS, SK, EX, file I/O, multi-step planning
- **Components**: `PL → RS(web_search ×2) → FG → TS → SK(register) → EX(forged tool) → EX(file_write) → OR(respond)`
- **Pass criteria**: File contains a coherent comparison sentence with real star counts and a percentage. All pipeline stages visible in trace. Tool persisted.
- **Notes**: The ultimate integration test. If this passes cleanly, Talos is working.

---

## Category 11 — Real-World Showcase

These are the queries you'd put in the README, record for a demo GIF, or show in a portfolio review. Every query is phrased the way a real human would type it — no mention of "forge", "vault", "primitives", or any internal machinery. The user just wants a result. Talos figures out the how.

> **Why these matter**: Categories 1–10 prove the engine works. Category 11 proves the engine is *worth building*. These are the "so what?" queries.
>
> **Design principle**: Most of these require Talos to **build a tool** to solve the problem. That's the differentiator — any chatbot can do a web search, but Talos writes, tests, and saves reusable utilities on the fly.

---

### Q51 · The data janitor — messy dates
- **Query**: `I have a list of dates in mixed formats: ["2025-01-15", "March 3, 2025", "15/06/2025", "2025.09.01", "Jan 7 2025"]. Normalize them all to YYYY-MM-DD.`
- **Tests**: Forger creates a multi-format date parser, Tester validates each format variant
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns all 5 dates in YYYY-MM-DD correctly. Tool persisted. Handles the ambiguous DD/MM vs MM/DD case reasonably.
- **Notes**: Every developer and analyst has done this by hand. The tool stays in the vault for any future date task.
- **Demo appeal**: Universal pain point. Gets a nod from any technical audience.

### Q52 · The CSV wrangler
- **Query**: `I have a CSV file at /tmp/sales.csv with columns: product, price, quantity. Add a new column called "revenue" that's price × quantity, and save the result to /tmp/sales_with_revenue.csv.`
- **Tests**: Forger builds a CSV column calculator, handles file I/O, Planner sequences read→transform→write
- **Components**: `PL → FG(csv column tool) → TS → SK(register) → EX → EX(file_write)`
- **Pass criteria**: Output CSV has 4 columns, revenue values are correct. Original file unchanged. Tool persisted.
- **Notes**: Setup: create a small test CSV before running. This is bread-and-butter data work — the kind of thing people open Excel for.
- **Setup**: `echo "product,price,quantity\nWidget A,10.50,100\nWidget B,24.99,50\nGadget C,5.00,500" > /tmp/sales.csv`
- **Demo appeal**: "I didn't write a single line of pandas. It just did it."

### Q53 · The log detective
- **Query**: `Parse this nginx-style log and tell me how many requests per HTTP status code: "GET /api 200\nPOST /login 401\nGET /home 200\nGET /api 500\nPOST /login 200\nGET /api 200\nGET /home 404\nPOST /login 401". Give me the counts sorted by frequency.`
- **Tests**: Forger builds a log parser + frequency counter, handles multi-line string input
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `200: 4, 401: 2, 500: 1, 404: 1`. Tool persisted for reuse on real log files later.
- **Notes**: DevOps/backend devs do this constantly. The forged tool is genuinely reusable.
- **Demo appeal**: Practical, unglamorous, exactly what real people need.

### Q54 · The JSON surgeon
- **Query**: `I have deeply nested JSON and I need it flat. Build something that takes nested JSON like {"user": {"name": "Yath", "address": {"city": "Mumbai", "zip": "400001"}}, "active": true} and flattens it to {"user.name": "Yath", "user.address.city": "Mumbai", "user.address.zip": "400001", "active": true}.`
- **Tests**: Recursive algorithm forging, handles nested dicts/lists, dot-notation key building
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Output matches expected flat structure exactly. Handles nested arrays too. Tool persisted.
- **Notes**: Common data pipeline task. Tests Forger's ability to write recursive code and Tester's ability to validate nested structures.
- **Demo appeal**: Anyone who's worked with APIs or databases knows this pain.

### Q55 · The text file analyzer
- **Query**: `I keep needing to analyze text files. Make me a tool that takes a file path and returns: total words, unique words, average word length, and the top 10 most frequent words with counts. Try it on /tmp/talos_upper.txt.`
- **Tests**: Non-trivial tool with file I/O + text processing + stats + sorting, Tester validates all metrics
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX(on test file)`
- **Pass criteria**: All 4 metrics returned and accurate. Top-10 list sorted correctly. Tool handles punctuation and casing. Persisted.
- **Notes**: Depends on /tmp/talos_upper.txt existing from Q27. A genuinely useful utility — "next time they say count words in X, it's instant."
- **Demo appeal**: Perfect for showing the "learns once, reuses forever" narrative.

### Q56 · The config transformer
- **Query**: `Convert this JSON config to YAML format: {"app": "talos", "version": "0.1.0", "settings": {"llm": "gpt-4o", "temperature": 0.7, "tools": ["web_search", "web_read", "python_exec"]}, "debug": false}. Save both the pretty-printed JSON and the YAML to /tmp/config.json and /tmp/config.yaml.`
- **Tests**: Forger builds JSON↔YAML converter, handles nested structures + arrays, dual file output
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX → EX(file_write ×2)`
- **Pass criteria**: Both files exist. JSON is valid and pretty-printed. YAML is valid and represents the same data. Tool persisted.
- **Notes**: DevOps daily bread. YAML module is stdlib — tests Forger's knowledge of available libraries.
- **Demo appeal**: Quick win that's immediately practical.

### Q57 · The slug machine
- **Query**: `I need a URL slug generator. It should take a title like "My Amazing Blog Post! (Part 2)" and return "my-amazing-blog-post-part-2". Handle special chars, multiple spaces, leading/trailing hyphens. Try it on "  LangGraph: Build Stateful AI Agents — A Guide! ".`
- **Tests**: String normalization, regex-heavy forging, edge case handling (leading/trailing whitespace, special chars)
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Returns `langgraph-build-stateful-ai-agents-a-guide`. No leading/trailing hyphens. No double hyphens. Tool persisted.
- **Notes**: Web devs forge this once and use it forever. Tests Tester's ability to catch edge cases (what about emoji? unicode?).
- **Demo appeal**: Small, sharp, useful. The kind of utility everyone's written at least once.

### Q58 · The batch renamer
- **Query**: `I have files in /tmp/rename_test/ and I want to rename them all by replacing spaces with underscores and converting to lowercase. Build a tool for this and run it.`
- **Tests**: Forger builds a file-system tool (Phase 2 territory — I/O tool), handles os.rename, Planner includes safety
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Files renamed correctly. No data loss. Tool handles "no files found" gracefully. Persisted.
- **Setup**: `mkdir -p /tmp/rename_test && touch "/tmp/rename_test/My Document.txt" "/tmp/rename_test/Photo From Trip.jpg" "/tmp/rename_test/REPORT Final.pdf"`
- **Notes**: Tests I/O tool forging — the Forger has to write code that interacts with the filesystem, not just pure computation.
- **Demo appeal**: Everyone has done this manually. "It just built me a batch renamer."

### Q59 · The diff detector
- **Query**: `Compare the files /tmp/talos_test.txt and /tmp/talos_upper.txt and tell me what changed between them. Show the differences clearly.`
- **Tests**: Forger builds a text diff tool, handles file reading + comparison + formatted output
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Correctly identifies that the content is the same text but one is uppercase. Diff output is human-readable. Tool persisted.
- **Notes**: Depends on Q05 and Q27 having created the two files. Tests Forger on a utility that requires reading two inputs and producing structured output.
- **Demo appeal**: "Built me a diff tool on the spot."

### Q60 · The markdown table builder
- **Query**: `Take this data and format it as a clean markdown table: headers are ["Agent", "Framework", "Key Feature"], rows are [["Talos", "LangGraph", "Self-evolving tools"], ["Voyager", "Custom", "Minecraft skills"], ["GenericAgent", "None", "Skill crystallization"]]. Save it to /tmp/comparison.md.`
- **Tests**: Forger builds a data→markdown-table formatter, handles alignment + escaping, file output
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX → EX(file_write)`
- **Pass criteria**: File contains a valid markdown table with proper alignment. All 3 rows present. Tool persisted for reuse.
- **Notes**: This tool becomes reusable anytime the agent needs to format structured data for display.
- **Demo appeal**: The output is visually verifiable. Nice for README screenshots.

### Q61 · The unit converter factory
- **Query**: `Build me a universal unit converter that handles: km↔miles, kg↔pounds, celsius↔fahrenheit, liters↔gallons. Convert 42km to miles, 100°F to celsius, and 75kg to pounds.`
- **Tests**: Multi-unit tool with a dispatch pattern, Forger handles multiple conversion formulas in one tool
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX(×3 conversions)`
- **Pass criteria**: 42km ≈ 26.1 miles, 100°F ≈ 37.78°C, 75kg ≈ 165.35 lbs. All within reasonable precision. Single tool handles all conversions. Persisted.
- **Notes**: Tests Forger's ability to create a tool with multiple "modes" and dispatch logic, similar to Q11 (Caesar) but more complex.
- **Demo appeal**: Useful forever. "It built me a Swiss army knife."

### Q62 · The regex helper
- **Query**: `I always mess up regexes. Build me a tool that takes a regex pattern and a test string, and returns: whether it matches, all match groups, and all match positions. Test it with pattern "(\d{3})-(\d{4})" on the string "Call 555-1234 or 800-5678 for help".`
- **Tests**: Forger builds a regex debugging utility, handles groups + positions + multiple matches
- **Components**: `PL → SK(search, miss) → FG → TS → SK(register) → EX`
- **Pass criteria**: Finds both matches (555-1234 and 800-5678). Groups extracted correctly (555, 1234, 800, 5678). Positions reported. Tool persisted.
- **Notes**: Regex debugging is a universal developer task. This tool is genuinely useful in the vault long-term.
- **Demo appeal**: "I never need regex101.com again" — every developer relates.

### Q63 · The second time is free — dates again
- **Query**: `Normalize these dates for me: ["December 25, 2025", "2025/04/01", "07-11-2025"].`
- **Tests**: Skill Manager finds the date normalizer forged in Q51, reuses without forging
- **Components**: `PL → SK(search, hit) → EX(vault tool)`
- **Pass criteria**: All 3 dates in YYYY-MM-DD. **No Forger invocation.** Vault tool reused. Faster than Q51.
- **Notes**: THIS is the demo moment. Run Q51, then Q63, and show the trace. "First time: built, tested, saved. Second time: found it, ran it instantly." That's the entire pitch.
- **Demo appeal**: The single best before/after in the suite. Lead with this in the README.

### Q64 · The compound workflow — no search needed
- **Query**: `Read the file /tmp/config.json, flatten the nested JSON structure, then generate a markdown table showing each key-value pair, and save it to /tmp/config_table.md.`
- **Tests**: Three vault tools chained (JSON flattener from Q54, markdown table from Q60) + file primitives. Planner builds a multi-step plan entirely from existing tools.
- **Components**: `PL → EX(file_read) → SK(search, hit) → EX(JSON flattener) → SK(search, hit) → EX(markdown table) → EX(file_write)`
- **Pass criteria**: Output file has a markdown table of flattened config key-values. **No forge triggered.** All tools reused from vault. Clean multi-step execution.
- **Notes**: Depends on Q56 (created config.json), Q54 (JSON flattener), Q60 (markdown table builder). This is the "compound reuse" flex — Talos chains 3 learned skills without building anything new.
- **Demo appeal**: "It already knew how to do every step." The payoff of skill accumulation.

### Q65 · The full showcase — everything fires
- **Query**: `Find the current top mass of the International Space Station, build a tool that converts kg to every common unit (pounds, ounces, grams, metric tons), run the conversion on the ISS mass, format the results as a markdown table, and save it to /tmp/iss_mass.md.`
- **Tests**: Every component type in one query — research (web_search), forge (converter), vault reuse (markdown table from Q60), file I/O, multi-step planning
- **Components**: `PL → RS(web_search) → FG(mass converter) → TS → SK(register) → EX(converter) → SK(search, hit for markdown table) → EX(table formatter) → EX(file_write)`
- **Pass criteria**: File contains a markdown table with ISS mass in 5 units. Research sourced a real number (~420,000 kg). New converter tool persisted. Markdown table tool reused. All stages visible in trace.
- **Notes**: The "everything works together" query. Research feeds into forge, forge feeds into executor, executor feeds into a vault tool, result gets saved. If this passes cleanly, Talos is ready to show.

---

## Execution Plan

### Phase 1 — Foundation (Q01–Q05)
Run all primitive tests first. If any fail, stop and fix before proceeding.

### Phase 2 — Core Loop (Q06–Q11)
Test forge→test→register. These populate the vault for later reuse tests.

### Phase 3 — Memory Validation (Q12–Q15)
Run immediately after Phase 2 to test vault reuse while tools are fresh.

### Phase 4 — Research Pipeline (Q16–Q25)
Test Researcher integration, both standalone and with Forger.

### Phase 5 — Composition (Q26–Q34)
Multi-step plans and mixed pipelines. Depends on vault having tools from Phases 2–4.

### Phase 6 — Human Interaction (Q35–Q37)
Test interrupt flows. May require manual interaction.

### Phase 7 — Resilience (Q38–Q43)
Error handling and edge cases. Can surface subtle bugs.

### Phase 8 — Boundaries (Q44–Q50)
Adversarial inputs and the engineering stress test. Run before showcase.

### Phase 9 — Real-World Showcase (Q51–Q65)
Run last. Needs a populated vault from earlier phases for Q63 and Q64 to demonstrate reuse. **These are your demo recording queries.** Best run as a continuous session for the full "skill accumulation" narrative.

---

## Tracking Template

For each query run, log:

```
Query ID: Q__
Status:   PASS / FAIL / PARTIAL
Time:     ___s
Components activated: [list]
Expected components:  [list]
Match:    YES / NO (component routing correct?)
Output:   [actual output]
Notes:    [anything unexpected]
```

---

## Coverage Matrix

| Component | Tested in queries |
|---|---|
| Planner | All queries (Q01–Q65) |
| Executor (primitives) | Q01–Q05, Q26–Q28, Q30, Q31, Q46, Q52, Q55, Q56, Q58, Q59, Q64 |
| Forger | Q06–Q11, Q15, Q21–Q25, Q28, Q29, Q33, Q38, Q39, Q41, Q50, Q51–Q62, Q65 |
| Tester | Q06–Q11, Q15, Q21–Q25, Q28, Q29, Q33, Q38, Q39, Q41, Q50, Q51–Q62, Q65 |
| Skill Manager (search) | Q06–Q15, Q21–Q25, Q29, Q31, Q32, Q34, Q42, Q48, Q49, Q51–Q65 |
| Skill Manager (register) | Q06–Q11, Q15, Q21–Q25, Q28, Q29, Q33, Q38, Q50, Q51–Q62, Q65 |
| Researcher (web_search) | Q01, Q16, Q18–Q20, Q23, Q26, Q28, Q33, Q35, Q43, Q50, Q65 |
| Researcher (web_read) | Q02, Q17, Q19, Q30 |
| Human input | Q35–Q37 |
| Orchestrator | All queries (routing + response) |
| Error handling | Q38–Q43, Q44–Q45 |
| Vault reuse | Q12–Q14, Q31, Q32, Q34, Q48, Q49, Q63, Q64 |
| Real-world tool forging | Q51–Q62 |
| Compound vault workflows | Q64, Q65 |
