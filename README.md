# astrbot_plugin_lolicon_image_master

AstrBot 随机涩图插件，支持 [lolicon API v2](https://api.lolicon.app/#/setu) 和 [mossia API](https://api.mossia.top/duckMo) 两种图源切换。

原作者仓库：[rikkamiss/astrbot_plugin_lolicon_image](https://github.com/rikkamiss/astrbot_plugin_lolicon_image)

## 功能

- `/setu`、`/色图`、`/涩图`、`/色色`、`/涩涩` — 随机涩图（支持关键词搜索）
- `/taisele`、`/不够色`、`/再色点`、`/不够涩` — R18 图片（需配置启用）
- `/setucd <秒>` — 设置冷却时间（持久化到配置文件）
- `/setu_help` — 查看帮助和当前配置
- LLM 工具自动注册：对话中提到"色图/涩图/来张图"等意图时 LLM 可自动调用

## 图源切换

通过 `api_provider` 配置项切换 API 提供方，两者请求/响应格式由插件自动适配：

| 能力 | lolicon | mossia |
|------|---------|--------|
| 默认地址 | `https://api.lolicon.app/setu/v2` | `https://api.mossia.top/duckMo` |
| 关键词搜索 | 多 tag 空格分隔（AND 取交集） | 仅作者名模糊搜索 |
| R18 模式 | 支持 0/1/2（含 mixed 混合） | 仅 0/1，mixed 自动降级为 0 |
| 排除 AI | 支持（excludeAI） | 支持（aiType=1） |

### 关键词搜索示例

lolicon：
```
/setu 猫娘 白丝
```

mossia（按作者名）：
```
/setu 作者名
```

## 配置项

安装后在 AstrBot 管理面板 → 插件配置页修改，所有选项均有默认值，开箱即用。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| api_provider | string | lolicon | API 提供方：lolicon / mossia |
| api_url | string | （空） | API 地址覆盖；留空时按 provider 自动选择默认地址，可填入自建反代 |
| cooldown | int | 10 | 冷却时间（秒），0 表示不限制 |
| cd_scope | string | user | 冷却范围：user / group |
| max_concurrency | int | 10 | 最大并发请求数 |
| request_timeout | int | 10 | 请求超时（秒） |
| api_size | string | regular | 向 API 请求的图片尺寸 |
| display_size | string | small | 消息端渲染尺寸 |
| proxy | string | （空） | HTTP 代理地址 |
| image_cdn_replace | string | （空） | 替换 pixiv 图片域名为自定义反代 |
| exclude_ai | bool | false | 排除 AI 生成图片 |
| show_image_info | bool | false | 随图展示标题/作者/PID/标签 |
| r18_mode | string | off | off / on / mixed |
| enable_r18_command | bool | true | 是否启用 /taisele 等 R18 指令 |
| r18_in_group | bool | false | 群聊是否允许 R18 |
| enable_llm_tool | bool | true | 向 LLM 注册 send_setu_image 工具 |
| tip_message | string | 来咯 👇 | 发图前的提示语，留空不发 |
| whitelist_users | list | [] | 用户白名单（启用后仅白名单可用） |
| whitelist_groups | list | [] | 群聊白名单 |
| blacklist_users | list | [] | 用户黑名单 |
| blacklist_groups | list | [] | 群聊黑名单 |
| r18_whitelist_users | list | [] | R18 用户白名单（启用后仅白名单用户可触发 R18） |
| r18_whitelist_groups | list | [] | R18 群聊白名单 |
| r18_blacklist_users | list | [] | R18 用户黑名单（即使 r18_mode=on 也禁止） |
| r18_blacklist_groups | list | [] | R18 群聊黑名单（即使 r18_in_group=true 也禁止） |

## 安装

将本目录放入 AstrBot 的 `addons/plugins/` 下，重启即可。
