# Voice typing

[Back to Poppy](../README.md)

Open **Settings → Voice typing**, enter a Groq or Gemini key, and enable the feature.

## Recording and shortcuts

The microphone next to the drawer’s other tools opens the recording pill. Click it to start, then use its
stop button to finish. For direct dictation into a field, focus the field and press **Ctrl+Alt+D** to start
or finish. Press **Ctrl+Alt+Shift+D** to cancel. Drag the pill to move it. Its position is remembered,
and you can reset it from the ready pill’s right-click menu.

Hold **Ctrl+Alt+Space** to record and release the keys to finish. For **Edit Mode**, select text in a supported
editable field and press **Ctrl+Alt+Shift+E**. Speak an instruction such as “make this shorter” and press the
shortcut again. Poppy sends the selection and instruction to the editing provider, then checks the original
selection again before replacing it. When the selection changes, the pill offers to copy the rewrite.

**Continuation context** is off by default. Enable it alongside **Clean up dictation** in Voice typing to send
up to 200 characters before the caret as reference for the cleanup provider. Poppy only inserts the new dictation.

## Transcription and recovery

With **Live transcript** on and a Gemini key, Poppy streams to Gemini Transcribe Live while you speak and uses
that session’s final transcript. When live streaming is unavailable, the existing providers can show a preview
in chunks and transcribe captured audio at Stop. During a longer recording, Poppy can save progress at a pause
when Gemini confirms the closed segment. After a disconnect it replays audio from the last confirmed
pause, or from the beginning if the provider has yet to confirm one. Optional cleanup runs on the combined text.

If transcription fails, click **Retry transcription** in the pill or **Retry last recording** in the tray.
The pill shows recovered text for you to copy. **Discard recording**, starting another take, and quitting Poppy
release the saved audio. Recovery keeps one recording of up to 90 seconds in memory.

Choose **Mixed languages** under **Speech languages** if you switch languages in a recording. Poppy reuses
a completed live transcript and sends text for formatting. When a longer mixed-language transcript is dominated
by Bengali or Devanagari script, Poppy can check the original audio again before formatting. The Hindi, Bengali and English
and Hindi, Marathi and English options also give Gemini language hints. **Writing system > Roman letters** uses
phonetic spelling in the final text, including Hinglish and Banglish, while keeping the spoken language.
If the transcription comes back in a different script, Poppy can use Windows’ built-in transliteration.

Poppy keeps the new dictation on the clipboard after sending it to another app. Without a verified editable field,
Poppy can copy the result to the clipboard. If the clipboard holds an image,
files, or other rich content, the pill offers a **Copy** button so you decide when to replace it. Automatic
copies stay out of Windows clipboard history, while an explicit copy can appear there.

## Providers and privacy

One Groq key covers transcription and optional cleanup. [Gemini](https://aistudio.google.com/apikey)
can back up both steps, and [OpenRouter](https://openrouter.ai/keys) can back up cleanup with its free router.
Settings accepts up to 15 keys or imports a JSON file using [this blank template](../examples/dictation-keys.example.json).
**Check keys** checks all entered credentials against provider metadata endpoints. This checks access without
sending a recording or running inference, and shows individual results by key number.

Keep any populated file private. Poppy encrypts saved keys with Windows. Audio goes to the selected
transcription provider and cleanup sends the transcript to the chosen editor. Free limits apply to your
provider account or project. Poppy respects rate-limit cooldowns and uses another configured provider.
