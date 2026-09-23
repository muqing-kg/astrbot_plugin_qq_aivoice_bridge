# QQ AI Voice Bridge - Source of Truth

Version: 0.1.0
Status: Active
Owner: 云霄

## 1. Scope

This plugin exposes QQ AI voice generation to AstrBot as a cross-platform TTS
provider.

It does not log in to QQ itself and does not modify NapCat or any other OneBot
implementation. It calls the existing OneBot actions exposed by the QQ
connection:

- `get_ai_characters`
- `get_ai_record`

The plugin may send the resulting audio to the current platform, or use a
configured QQ relay group for platforms without a native QQ group context.

Non-goals:

- No QQ singing mode in v0.1.0. The current upstream actions hard-code
  `AIVoiceChatType.Sound`.
- No voice cloning or text-to-voice design.
- No automatic semantic decision about whether a platform is QQ. The user
  explicitly configures QQ platform instance IDs. An empty selection means all
  platforms are treated as QQ for backward compatibility with QQ-only users.
- No external HTTP TTS service in v0.1.0.

## 2. Domain Model

### 2.1 Platform Instance

An AstrBot platform adapter instance identified by its configured `id`.

Invariants:

- A platform instance ID is the only supported identity for platform routing.
- `aiocqhttp` is a transport type, not proof that the platform is QQ.
- If `qq_platforms` is empty, every platform instance is treated as QQ.
- If `qq_platforms` is non-empty, only listed instances are treated as QQ.

### 2.2 QQ Relay Group

A group ID used as the generation context when the current event is not a
native QQ group.

Invariants:

- It must be a group the selected QQ bot can access.
- It is required for QQ private chats and non-QQ platforms.
- It may be empty only when every routed event already has a usable QQ group.

### 2.3 Voice Role

A QQ AI voice role identified by `character_id`, with a user-facing
`character_name`.

The plugin ships with the verified built-in role list and treats it as a
fallback only. Runtime role lookup is authoritative because QQ may change the
available roles.

Resolution priority:

1. Per-group override stored by the plugin.
2. Global default role from config.
3. First role returned by the current QQ group.

### 2.4 Audio Artifact

The downloaded audio for one synthesized text segment.

Invariants:

- Cache key is `character_id + output_format + text`.
- The cache stores bytes, never a QQ URL.
- The output format is one of `silk`, `wav`, `mp3`.
- If the source is already the target format, no conversion is performed.

## 3. Core Invariants

1. QQ-side code is never modified.
2. The current platform is chosen by AstrBot event metadata.
3. The QQ platform is selected by configured platform instance IDs, with
   empty-list means-all-QQ semantics.
4. A native QQ group uses its own group ID.
5. Every other routed event uses the relay group.
6. A failed direct group attempt may fall back to the relay group.
7. A failed generation falls back to text when the relevant fallback switch
   allows it.
8. User-facing role commands only operate on QQ groups.
9. Group overrides are keyed by `platform_id + group_id`.
10. Generated URLs are never persisted.

## 4. Decisions

### D-001: Reuse OneBot actions instead of adding a QQ-side service

Decision: Call `get_ai_record` on the existing NapCat connection.

Why: It avoids introducing a second QQ client, preserves the "QQ side does
not process anything" constraint, and matches the proven behavior in
`astrbot_plugin_record_converter`.

Rejected alternative: A separate local QQ service or NapCat fork.

### D-002: Explicit platform selection with all-QQ default

Decision: `qq_platforms` is a multi-select list. Empty list means all
platforms are treated as QQ; a non-empty list narrows the QQ scope.

Why: Most deployments only use QQ, while mixed-platform deployments need an
override. This follows the user's stated product priority.

### D-003: Static built-in role list plus runtime lookup

Decision: Ship the verified 22-role list as config/fallback data, but always
prefer the role list returned by QQ at runtime.

Why: The static list works offline and gives a usable config page; live data
handles server changes and account-specific availability.

### D-004: `pilk` for SILK, FFmpeg for MP3

Decision: Decode SILK with `pilk`; use FFmpeg for MP3 encoding.

Why: Python does not provide SILK support in the standard library. `pilk` is a
small Python dependency; FFmpeg is already common in AstrBot deployments.

### D-005: URL cache is forbidden

Decision: Cache only downloaded bytes.

Why: QQ download URLs carry `rkey` and expire.

