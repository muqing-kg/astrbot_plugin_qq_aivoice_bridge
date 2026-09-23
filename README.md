# QQ 声聊跨平台 TTS

调用 NapCat/OneBot 已开放的 QQ AI 声聊接口，把生成音频发送到当前
AstrBot 平台。插件不登录 QQ，不修改 NapCat，也不要求第三方 TTS Key。

## 依赖

- AstrBot `>=4.26,<5`
- NapCat 或实现了以下扩展 action 的 OneBot 实现：
  - `get_ai_characters`
  - `get_ai_record`
- Python `aiohttp`
- Python `silk-python`
- FFmpeg，用于 WAV/MP3 转换

## 工作规则

- QQ 群聊：直接使用当前群，不需要 QQ 中转群。
- QQ 私聊：必须配置 QQ 中转群。
- 其他平台：使用 QQ 中转群。
- “识别为 QQ 的平台”留空时，所有平台默认按 QQ 处理。
- 多平台部署时，在“识别为 QQ 的平台”里逐个填真正的 QQ 平台实例 ID。

## 配置

配置项包含：

- 基础设置：总开关、QQ 平台列表、QQ 中转群、默认角色、输出格式。
- 输出设置：自动 TTS、概率、文字同发、异步发送、长度限制。
- 文本分段：开关、规则、数量上限、语音概率、文字兜底。
- 口播润色：LLM 开关、展示文本、Provider、提示词。
- 高级设置：超时、重试、并发、FFmpeg 路径。

“总开关”关掉后插件完全不工作，“自动 TTS”关掉后只保留“声聊角色”命令。

内置角色来自 QQ 实时返回的角色清单。运行时仍优先使用
`get_ai_characters` 的最新结果。

## 本地文件

插件不保留任何音频文件。

- 合成出来的音频写到插件数据目录的 `temp/`，发送完成后立即删除，失败也同样删除。
- 插件启动时会清空 `temp/`，收掉上次崩溃残留；旧版本升级上来的 `cache/` 目录也会一并清除。
- 重复文本的缓存放在进程内存里，不落盘，上限 128 条 / 32MB / 1 小时，重启即清空。
- 唯一写盘的文件是 `state.json`，只存各群单独指定的声聊角色，不含音频。

## 命令

“声聊角色”是管理员命令，需要 AstrBot 管理员权限。

```text
声聊角色
```

返回当前 QQ 群可用角色，一行一个，带序号。

```text
声聊角色 6
声聊角色 妲己
```

为当前群设置独立角色。该设置不受全局默认角色影响。

```text
声聊角色 重置
```

清除当前群角色覆盖，恢复跟随全局默认角色。

## 说明

- QQ 群聊直用当前群时，QQ 服务端会直接发送 AI 语音，插件不会重复发送。
- 其他平台模式下，插件下载音频并按配置转换成 `silk`、`wav` 或 `mp3`。
- QQ 返回的下载 URL 带时效参数。插件只把音频字节本身放进内存缓存，不保存 URL。
- 语音合成或发送失败时，本条会改发原文文字，不会静默丢消息。

## 参考项目

- [SteveBaka/astrbot_plugin_mimo_tts](https://github.com/SteveBaka/astrbot_plugin_mimo_tts)：分段、润色和配置交互思路参考，MIT License。
- [zgojin/astrbot_plugin_AIQTalk](https://github.com/zgojin/astrbot_plugin_AIQTalk)：QQ AI 角色调用方式参考。
- [Zhalslar/astrbot_plugin_record_converter](https://github.com/Zhalslar/astrbot_plugin_record_converter)：QQ AI 语音 URL 获取和转发思路参考。
