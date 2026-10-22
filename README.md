# role-leak-detector

English | [日本語](README.ja.md)

A single-file `Stop` hook for Claude Code that detects **fake `user` turns**
(role-boundary leaks) in the assistant's own output. No dependencies.

https://github.com/user-attachments/assets/b3e1eeb0-43f0-48ee-85bc-e067be7dedc3

**Install:** copy `detect-fake-user.py` to `~/.claude/hooks/` and register it as a `Stop` hook in `~/.claude/settings.json` (see [Install](#install) below).
**Output:** `~/.claude/hooks/detections.log`. It logs and beeps; it never alters the session.
**Caveat:** heuristic. A nonexistent-path hit may just be a directory the assistant proposed but has not created yet.

Related: [anthropics/claude-code#44778](https://github.com/anthropics/claude-code/issues/44778)

> **Timestamps are in JST.** Log lines and the on-screen warning are in English. Text quoted
> from your session is logged as-is, in whatever language it was written.

---

## What it finds

Once in a while, Claude Code **ends its own reply with what the user would probably say next**.
On screen it looks like something you said. In the transcript it is still `role: assistant`.

```
(assistant's reply)
…

user sounds good, go ahead          ← nobody typed this
```

In the author's logs this happened in **23 of 3,790 messages (0.61%)**. Most are harmless
acknowledgements, but some show up as **an approval, an instruction, or an attributed source**.

## The 4 + 1 axes

| | What it checks |
|---|---|
| Label leak | `user` / `système` at the start of a line. Also catches forms with no separator, such as `user1000円` or `user一応、` |
| Script mixing | Cyrillic, Greek, Hangul, Thai and others (eight scripts), plus Simplified Chinese characters that Japanese does not use. This is the case where **the meaning is right and only the language is wrong**, as in `формальな書類` |
| Nonexistent path | Checks whether local paths in the output actually exist (**no network access**) |
| URL record | Appends URLs found in the output to `refs.log`. It records them and makes no judgement |
| Unfinished reply | The previous assistant message has no `stop_reason`, meaning generation was cut off. **The only axis that involves no guessing** (disabled on the CLI; see below) |

The script-mixing axis was built against Japanese and English sessions. If you work in one of
the listed scripts, that axis will fire on your normal text.

## What it cannot detect (important)

- **Fabrications with no label.** They exist: one case continued, unlabelled, right after a
  label leak. There is no way to estimate how many.
- **Text that appeared on screen but was not saved to the log.** The reverse also happened: a
  label shown by the UI was saved as part of the message body. The UI and the transcript
  **do not match in either direction**.
- **A real user message that was absorbed into the assistant side.** Both cases look the same:
  `user` at the start of a line inside an assistant message.
- **An accepted input suggestion.** That is recorded as a normal `role: user` message, so it
  leaves no trace.
- **"Unfinished reply" on the CLI.** On the CLI (`entrypoint: cli`), the previous assistant
  record sometimes has no `stop_reason` yet at the moment the `Stop` hook runs, so this one axis
  is disabled automatically. Counting the saved `.jsonl` files afterwards showed zero missing
  values on the CLI as well (1,563 records from 2.1.267–268), so this is a matter of timing at
  hook time and not a gap in the record. The other four axes work on the CLI unchanged.

## Install

```bash
mkdir -p ~/.claude/hooks
curl -o ~/.claude/hooks/detect-fake-user.py \
  https://raw.githubusercontent.com/npulsar-droid/role-leak-detector/main/detect-fake-user.py
```

Add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/hooks/detect-fake-user.py" } ] }
    ]
  }
}
```

**The exit code is always 0.** It never blocks the stop (`exit 2` is not used because it can
cause a loop).

## Output

```
~/.claude/hooks/detections.log     detections (kept permanently)
~/.claude/hooks/refs.log           URLs that appeared in the output
~/.claude/hooks/invocations.log    one line per run (delete that block in the script if you don't want it)
```

On a detection it plays **a system sound on macOS** and the terminal bell elsewhere.
Set `CLAUDE_DETECT_SOUND=0` to turn the sound off.

Whether anything appears on screen depends on the environment (`systemMessage` has been seen to
display in the desktop app). **Even when nothing is displayed, the detection is always written
to `detections.log`.**

## Scan past logs

```bash
python3 ~/.claude/hooks/detect-fake-user.py --test ~/.claude/projects/<project>/<session>.jsonl
```

## Count the conditions in your own logs

`leak_context_stats.py` reads every `~/.claude/projects/**/*.jsonl`, computes features for each
assistant message, and prints tables showing **under which conditions leaks are more likely**.

```bash
python3 leak_context_stats.py
```

It reports a detection rate by context length, depth of the agentic turn, type of the preceding
record, seconds since the last human message, number of earlier leaks in the session, distance
from the last compaction, model, date, and so on. It also writes `feat.csv` (one row per
assistant message) to the working directory.

**`feat.csv` contains fragments of your own logs.** Each row holds the first 80 characters of the
assistant message, so do not share the file as it is (this repository lists it in `.gitignore`).
Drop the `head` column before sharing. The summary tables themselves contain no message text.

The numbers in the [follow-up report on #44778](https://github.com/anthropics/claude-code/issues/44778)
come from running this script on the author's logs. **One person's data cannot separate the
conditions**, so it would help if you posted your results on the issue.

## Check a message you don't remember sending

```bash
grep -h "<the text you don't recognize>" ~/.claude/projects/**/*.jsonl \
  | python3 -c "import json,sys; [print(json.loads(l)['message']['role']) for l in sys.stdin]" \
  | sort | uniq -c
```

If only `assistant` comes back, the message was fabricated: no `role: user` record exists for it.

## Common false positives

The detector does not see fabrication itself. It looks for **traces** that tend to accompany it.
A beep does not prove a fabrication. A person reads `detections.log` and decides.

- **Nonexistent path** also fires on a proposal to create a directory that does not exist yet
  ("let's create `~/.agent-log-backup/`"), on example paths (`~/Desktop/xxx.png`), and on
  abbreviated paths (`.../hooks/detect-fake-user.py`). Most false positives in real use come
  from this axis.
- **Script mixing** also fires when a foreign language is quoted or translated as-is.
- **Unfinished reply** is disabled on the CLI, but in the desktop app it also fires on a reply
  you stopped with Esc.

On a detection it does not stop the session or rewrite any text. It writes to the log and plays
a sound.

## Note

All **five** holes found in the detector so far were found by real occurrences. None came up in
desk testing. There are probably more. Issues and PRs are welcome.

## License

MIT
