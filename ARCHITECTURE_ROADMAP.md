# QQ AI Voice Bridge - Architecture Roadmap

Version: 0.1.0
Status: Active
Owner: 沐倾

## 0. Executive Context

The plugin turns text into QQ AI voice and delivers it to the AstrBot
platform that produced the event. QQ is used only as the voice generation
backend. The relay group is the bridge for QQ private chats and non-QQ
platforms.

## 1. Tech Stack

| Layer | Tech | Role |
|---|---|---|
| AstrBot plugin | Python 3.10+ | lifecycle, event hooks, commands |
| QQ bridge | aiocqhttp / NapCat OneBot | `get_ai_characters`, `get_ai_record` |
| Audio | `silk-python`, `wave`, FFmpeg | SILK/WAV/MP3 conversion |
| State | JSON files | role overrides, cache metadata, optional session state |
| UI | AstrBot config schema + optional plugin page | static options, dynamic platform list |

## 2. Data Schema

### 2.1 Plugin State

`data/plugin_data/astrbot_plugin_qq_aivoice_bridge/state.json`

```json
{
  "group_roles": {
    "<platform_id>": {
      "<group_id>": "<character_id>"
    }
  },
  "role_cache": {
    "<platform_id>": {
      "<group_id>": {
        "updated_at": 0,
        "characters": [
          {"character_id": "lucy-voice-f36", "character_name": "温柔妹妹"}
        ]
      }
    }
  }
}
```

### 2.2 Audio Cache

`data/plugin_data/astrbot_plugin_qq_aivoice_bridge/cache/`

Cache key:

```text
sha256(character_id + "\0" + output_format + "\0" + text)
```

### 2.3 Config Surface

The config page follows the MiMO TTS grouping style:

- Basic: plugin enabled, QQ platform list, relay group, default role, format.
- Output: auto TTS, probability, text sending, min/max length.
- Segmentation: enabled, pattern, max count, per-segment probability,
  fallback.
- Polish: enabled, display polished text, provider, prompt.
- Advanced: timeout, retries, concurrency, cache TTL, ffmpeg path.

## 3. Backend

### 3.1 Modules

| Module | Responsibility |
|---|---|
| `main.py` | plugin lifecycle, hooks, command registration |
| `core/config.py` | flatten config, typed accessors, defaults |
| `core/roles.py` | built-in role registry and role resolution |
| `core/qq_voice.py` | platform lookup, role list, `get_ai_record`, download |
| `core/audio.py` | format sniffing, conversion, cache |
| `core/pipeline.py` | text cleaning, polish, segmentation, send decisions |
| `core/state.py` | group role overrides and role cache |
| `handlers/commands.py` | status and role commands |
| `webapi.py` | platform list and config helpers for the plugin page |

### 3.2 Runtime Flow

```text
on_decorating_result
  -> enabled / probability / length checks
  -> extract plain text
  -> optional LLM polish
  -> optional segmentation
  -> resolve route:
       selected QQ platform + group -> current group
       otherwise -> relay group
  -> resolve role:
       group override > global default > first live role
  -> get_ai_record
  -> download URL to bytes
  -> convert to requested format
  -> send Record or File to current platform
```

### 3.3 Failure Paths

| Failure | Behavior |
|---|---|
| Missing QQ platform | fall back to relay group or text |
| Missing relay group | text fallback |
| Empty role list | try relay group; otherwise text |
| `get_ai_record` error | clear role cache, retry relay, otherwise text |
| SILK decode failure | send source SILK if allowed, otherwise text |
| MP3 encoder missing | keep WAV, log warning |
| URL expired | re-request once, never report URL to user |

## 4. Frontend

### 4.1 Native Config Page

Native schema is used for all static settings and the built-in role dropdown.

### 4.2 Dynamic Platform List

A small plugin page or web API exposes the current AstrBot platform instances.
The user can multi-select instances to mark them as QQ. Empty selection has
the documented all-QQ default.

## 5. Execution Phases

1. Project docs and package skeleton.
2. Pure role/config/audio-format logic and tests.
3. QQ platform discovery, role lookup, `get_ai_record`, download.
4. Audio conversion and cache.
5. Auto-TTS hook and role commands.
6. Dynamic platform page.
7. Integration tests against a mocked OneBot client.

## 6. Non-Functional Requirements

- No secret values in logs.
- Bounded concurrency for QQ generation.
- Cache and temp-file cleanup.
- No blocking network or FFmpeg calls on the event loop.
- All user text shown in the current platform must be plain text; audio tags
  are stripped.
