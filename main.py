import asyncio
import base64
import json
import re
from typing import Optional, Tuple

import httpx
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


DEFAULT_API_URLS = {
    "lolicon": "https://api.lolicon.app/setu/v2",
    "mossia": "https://api.mossia.top/duckMo",
}


@dataclass
class SendSetuTool(FunctionTool[AstrAgentContext]):
    name: str = "send_setu_image"
    description: str = (
        "当用户想要色图、涩图、二次元图片、老婆图、萌图、setu，"
        "或者让你来一张相关图片时，调用此工具发送图片。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "图片搜索标签，例如猫娘、白丝、萝莉；多个标签用空格分隔；没有则留空",
                },
                "r18": {
                    "type": "boolean",
                    "description": "是否获取 R18 图片。普通涩图填 false，明确要求 R18/更色一点时填 true",
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        ctx = context.context.context
        event = context.context.event

        keyword = str(kwargs.get("keyword", "") or "").strip()
        r18 = bool(kwargs.get("r18", False))

        plugin = SetuPlugin._plugin_instance
        if plugin is None:
            return "涩图插件未正确加载，无法发送图片。"

        if not plugin._is_allowed(event):
            return "当前会话没有使用涩图功能的权限。"

        if r18 and not plugin._is_r18_allowed(event):
            r18 = False

        url, info = await plugin.fetch_setu(r18=r18, keyword=keyword, event=event)
        if not url.startswith("http"):
            return url

        try:
            mc = MessageChain()
            tip = (plugin.config.get("tip_message", "来咯 👇") or "").strip()
            if tip:
                mc = mc.message(tip)
            b64 = await plugin._download_image_b64(url)
            if b64:
                mc = mc.image(f"base64://{b64}")
            else:
                mc = mc.image(url)
            if plugin.config.get("show_image_info", False) and info:
                mc = mc.message("\n" + info)
            await ctx.send_message(event.unified_msg_origin, mc)
            kind = "R18" if r18 else "普通"
            if keyword:
                return f"已成功发送一张{kind}图片，关键词：{keyword}。"
            return f"已成功发送一张{kind}图片。"
        except Exception as e:
            logger.error(f"[SetuPlugin] LLM 工具发送图片失败: {e}")
            return f"发送图片失败: {e}"


@register("setu", "FateTrial", "一个发送随机涩图的插件", "2.2.0")
class SetuPlugin(Star):
    _plugin_instance: Optional["SetuPlugin"] = None

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        SetuPlugin._plugin_instance = self
        self.config = config if config is not None else {}
        self.last_usage: dict = {}
        max_concurrency = max(1, int(self.config.get("max_concurrency", 10) or 10))
        self.semaphore = asyncio.Semaphore(max_concurrency)

        if self.config.get("enable_llm_tool", True):
            try:
                self.context.add_llm_tools(SendSetuTool())
            except Exception as e:
                logger.warning(f"[SetuPlugin] 注册 LLM 工具失败：{e}")

    @property
    def cd(self) -> int:
        return int(self.config.get("cooldown", 10) or 0)

    def _save_config(self):
        try:
            if hasattr(self.config, "save_config"):
                self.config.save_config()
        except Exception as e:
            logger.warning(f"[SetuPlugin] 保存配置失败：{e}")

    def _scope_key(self, event: AstrMessageEvent) -> str:
        scope = self.config.get("cd_scope", "user")
        if scope == "group":
            gid = event.get_group_id()
            if gid:
                return f"group:{gid}"
        return f"user:{event.get_sender_id()}"

    def _is_r18_allowed(self, event: AstrMessageEvent) -> bool:
        mode = self.config.get("r18_mode", "off")
        if mode == "off":
            return False
        if not self.config.get("r18_in_group", False) and event.get_group_id():
            return False

        uid = str(event.get_sender_id() or "")
        gid = str(event.get_group_id() or "")

        r18_bl_users = [str(x) for x in (self.config.get("r18_blacklist_users") or [])]
        r18_bl_groups = [str(x) for x in (self.config.get("r18_blacklist_groups") or [])]
        if uid and uid in r18_bl_users:
            return False
        if gid and gid in r18_bl_groups:
            return False

        r18_wl_users = [str(x) for x in (self.config.get("r18_whitelist_users") or [])]
        r18_wl_groups = [str(x) for x in (self.config.get("r18_whitelist_groups") or [])]
        if r18_wl_users or r18_wl_groups:
            if uid and uid in r18_wl_users:
                return True
            if gid and gid in r18_wl_groups:
                return True
            return False

        return True

    def _is_allowed(self, event: AstrMessageEvent) -> bool:
        uid = str(event.get_sender_id() or "")
        gid = str(event.get_group_id() or "")

        wl_users = [str(x) for x in (self.config.get("whitelist_users") or [])]
        wl_groups = [str(x) for x in (self.config.get("whitelist_groups") or [])]
        bl_users = [str(x) for x in (self.config.get("blacklist_users") or [])]
        bl_groups = [str(x) for x in (self.config.get("blacklist_groups") or [])]

        if uid and uid in bl_users:
            return False
        if gid and gid in bl_groups:
            return False
        if wl_users or wl_groups:
            if uid and uid in wl_users:
                return True
            if gid and gid in wl_groups:
                return True
            return False
        return True

    def _resolve_r18_param(self, want_r18: bool, event: Optional[AstrMessageEvent] = None) -> int:
        mode = self.config.get("r18_mode", "off")
        if mode == "off":
            return 0
        if event is not None:
            if not self.config.get("r18_in_group", False) and event.get_group_id():
                return 0
            if not self._is_r18_allowed(event):
                return 0
        if want_r18:
            return 1
        if mode == "mixed":
            return 2
        return 0

    def _get_provider(self) -> str:
        provider = (self.config.get("api_provider") or "lolicon").strip().lower()
        if provider not in DEFAULT_API_URLS:
            provider = "lolicon"
        return provider

    def _get_api_url(self, provider: str) -> str:
        custom = (self.config.get("api_url") or "").strip()
        if custom:
            return custom
        return DEFAULT_API_URLS[provider]

    async def _http_get_json(self, url: str, params):
        timeout = float(self.config.get("request_timeout", 10) or 10)
        proxy = (self.config.get("proxy") or "").strip()
        client_kwargs = {"timeout": timeout}
        if proxy:
            try:
                client = httpx.AsyncClient(proxy=proxy, **client_kwargs)
            except TypeError:
                client = httpx.AsyncClient(proxies=proxy, **client_kwargs)
        else:
            client = httpx.AsyncClient(**client_kwargs)
        async with client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _download_image_b64(self, url: str) -> Optional[str]:
        timeout = float(self.config.get("request_timeout", 10) or 10)
        proxy = (self.config.get("proxy") or "").strip()
        client_kwargs = {"timeout": timeout, "follow_redirects": True}
        if proxy:
            try:
                client = httpx.AsyncClient(proxy=proxy, **client_kwargs)
            except TypeError:
                client = httpx.AsyncClient(proxies=proxy, **client_kwargs)
        else:
            client = httpx.AsyncClient(**client_kwargs)
        try:
            async with client:
                resp = await client.get(url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "image" not in content_type and not self._url_has_image_ext(url):
                    logger.warning(f"[SetuPlugin] 下载内容非图片: {content_type}")
                    return None
                return base64.b64encode(resp.content).decode()
        except Exception as e:
            logger.error(f"[SetuPlugin] 下载图片失败: {e}")
            return None

    @staticmethod
    def _url_has_image_ext(url: str) -> bool:
        path = url.split("?")[0].split("#")[0].lower()
        return any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))

    async def _request_lolicon(self, r18: int, keyword: str):
        api_url = self._get_api_url("lolicon")
        api_size = (self.config.get("api_size") or "regular").strip() or "regular"
        exclude_ai = bool(self.config.get("exclude_ai", False))

        params: list = [
            ("r18", r18),
            ("num", 1),
            ("size", api_size),
            ("excludeAI", "true" if exclude_ai else "false"),
        ]
        if keyword:
            for tag in (t for t in keyword.split() if t):
                params.append(("tag", tag))
        return await self._http_get_json(api_url, params)

    async def _request_mossia(self, r18: int, keyword: str):
        api_url = self._get_api_url("mossia")
        api_size = (self.config.get("api_size") or "regular").strip() or "regular"
        exclude_ai = bool(self.config.get("exclude_ai", False))

        params: list = [
            ("num", 1),
            ("sizeList", api_size),
            ("r18Type", 1 if r18 else 0),
        ]
        if exclude_ai:
            params.append(("aiType", 1))
        if keyword:
            params.append(("author", keyword.strip()))
        return await self._http_get_json(api_url, params)

    def _parse_lolicon(self, data: dict) -> Tuple[str, str, dict]:
        items = data.get("data") or []
        if not items:
            return "", "", {}
        item = items[0]
        urls = item.get("urls") or {}
        api_size = (self.config.get("api_size") or "regular").strip() or "regular"
        url = urls.get(api_size) or next(iter(urls.values()), "")
        return url, self._format_lolicon_info(item), item

    def _parse_mossia(self, data: dict) -> Tuple[str, str, dict]:
        items = data.get("data") or []
        if not items:
            return "", "", {}
        item = items[0]
        url_list = item.get("urlsList") or []
        api_size = (self.config.get("api_size") or "regular").strip() or "regular"
        url = ""
        for u in url_list:
            if (u.get("urlSize") or "").lower() == api_size.lower():
                url = u.get("url") or ""
                break
        if not url and url_list:
            url = url_list[0].get("url") or ""
        return url, self._format_mossia_info(item), item

    def _format_lolicon_info(self, item: dict) -> str:
        title = item.get("title") or ""
        author = item.get("author") or ""
        pid = item.get("pid")
        tags = item.get("tags") or []
        tag_str = "、".join(tags[:6])
        return self._join_info_parts(title, author, pid, tag_str)

    def _format_mossia_info(self, item: dict) -> str:
        title = item.get("title") or ""
        author = item.get("author") or ""
        pid = item.get("pid")
        tags_list = item.get("tagsList") or []
        names = []
        for t in tags_list[:6]:
            n = t.get("tagName") or t.get("tagEn") or ""
            if n:
                names.append(n)
        return self._join_info_parts(title, author, pid, "、".join(names))

    def _join_info_parts(self, title: str, author: str, pid, tag_str: str) -> str:
        parts = []
        if title:
            parts.append(f"标题：{title}")
        if author:
            parts.append(f"作者：{author}")
        if pid:
            parts.append(f"PID：{pid}")
        if tag_str:
            parts.append(f"标签：{tag_str}")
        return " | ".join(parts)

    def _maybe_replace_cdn(self, url: str) -> str:
        cdn = (self.config.get("image_cdn_replace") or "").strip().rstrip("/")
        if not cdn or not url:
            return url
        for src in ("i.pixiv.re", "i.pximg.net", "i.pixiv.cat"):
            if src in url:
                return url.replace(src, cdn)
        return url

    async def fetch_setu(
        self,
        r18: bool = False,
        keyword: str = "",
        event: Optional[AstrMessageEvent] = None,
    ) -> Tuple[str, str]:
        provider = self._get_provider()
        try:
            r18_param = self._resolve_r18_param(r18, event)
            if provider == "mossia":
                data = await self._request_mossia(r18=r18_param, keyword=keyword)
                if isinstance(data, dict) and data.get("success") is False:
                    msg = data.get("message") or data.get("errCode") or "请求失败"
                    return f"错误信息：{msg}", ""
                url, info, _ = self._parse_mossia(data)
            else:
                data = await self._request_lolicon(r18=r18_param, keyword=keyword)
                if isinstance(data, dict) and data.get("error"):
                    return f"错误信息：{data.get('error')}", ""
                url, info, _ = self._parse_lolicon(data)

            if not url:
                hint = "可以换个关键词再试。" if provider == "lolicon" else "mossia 仅支持作者名搜索，可改用空关键词。"
                return f"没找到合适的图片，{hint}", ""
            return self._maybe_replace_cdn(url), info
        except httpx.HTTPStatusError as e:
            return f"错误信息：获取涩图时发生 HTTP 错误：{e.response.status_code}", ""
        except httpx.TimeoutException:
            return "错误信息：获取涩图超时，请稍后重试。", ""
        except httpx.HTTPError as e:
            return f"错误信息：网络错误：{e}", ""
        except json.JSONDecodeError as e:
            return f"错误信息：解析返回数据失败：{e}", ""
        except Exception as e:
            logger.exception("[SetuPlugin] fetch_setu 未知错误")
            return f"错误信息：发生未知错误：{e}", ""

    async def fetch_setu_url(self, r18: bool = False, keyword: str = "") -> str:
        url, _ = await self.fetch_setu(r18=r18, keyword=keyword)
        return url

    def _extract_keyword(self, message: str, command_names: set) -> str:
        text = (message or "").strip()
        for command_name in command_names:
            for prefix in (f"/{command_name}", command_name):
                if text == prefix:
                    return ""
                if text.startswith(prefix + " "):
                    return text[len(prefix):].strip()

        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            return parts[1].strip()
        return ""

    async def _handle_setu_request(
        self, event: AstrMessageEvent, r18: bool, command_names: set
    ):
        if not self._is_allowed(event):
            yield event.plain_result("当前会话没有使用涩图功能的权限。")
            return

        if r18 and not self._is_r18_allowed(event):
            yield event.plain_result("当前环境下 R18 已被禁用。")
            return

        scope_key = self._scope_key(event)
        now = asyncio.get_event_loop().time()
        cd = self.cd
        if cd > 0 and scope_key in self.last_usage and (now - self.last_usage[scope_key]) < cd:
            remaining = cd - (now - self.last_usage[scope_key])
            cd_tip = (self.config.get("cd_tip_message") or "急什么，罚你停鹿 {remaining} 秒").strip()
            try:
                msg = cd_tip.format(remaining=f"{remaining:.1f}", cd=cd)
            except (KeyError, ValueError):
                msg = f"冷却中，请等待 {remaining:.1f} 秒"
            yield event.plain_result(msg)
            return

        keyword = self._extract_keyword(event.message_str, command_names)

        async with self.semaphore:
            url, info = await self.fetch_setu(r18=r18, keyword=keyword, event=event)
            if not url.startswith("http"):
                yield event.plain_result(url)
                return

            tip = (self.config.get("tip_message", "来咯 👇") or "").strip()
            if tip:
                yield event.plain_result(tip)

            b64 = await self._download_image_b64(url)
            if b64:
                chain = [Image.fromBase64(b64)]
            else:
                try:
                    chain = [Image.fromURL(url)]
                except Exception:
                    yield event.plain_result("图片下载失败，请稍后重试。")
                    return
            yield event.chain_result(chain)

            if self.config.get("show_image_info", False) and info:
                yield event.plain_result(info)

            self.last_usage[scope_key] = now

    @filter.command("setu", alias={"色图", "涩图", "色色", "涩涩"})
    async def setu(self, event: AstrMessageEvent):
        async for result in self._handle_setu_request(
            event, r18=False, command_names={"setu", "色图", "涩图", "色色", "涩涩"}
        ):
            yield result

    @filter.command("taisele", alias={"不够色", "再色点", "不够涩"})
    async def taisele(self, event: AstrMessageEvent):
        if not self.config.get("enable_r18_command", True):
            yield event.plain_result("R18 指令已被管理员禁用。")
            return
        async for result in self._handle_setu_request(
            event, r18=True, command_names={"taisele", "不够色", "再色点", "不够涩"}
        ):
            yield result

    @filter.command("setucd")
    async def set_setu_cd(self, event: AstrMessageEvent, cd: int):
        if cd < 0:
            yield event.plain_result("冷却时间必须 ≥ 0。")
            return
        self.config["cooldown"] = cd
        self._save_config()
        yield event.plain_result(f"涩图指令冷却时间已设置为 {cd} 秒（已写入配置）。")

    @filter.command("setu_help")
    async def setu_help(self, event: AstrMessageEvent):
        cfg = self.config
        help_text = f"""**涩图插件帮助**

**可用命令:**
- `/setu`、`/色图`、`/涩图`、`/色色`、`/涩涩`：发送一张随机涩图。
- `/setu 关键词`：按标签搜索（多个标签用空格分隔，例如 `/setu 猫娘 白丝`）。
- `/taisele`、`/不够色`、`/再色点`、`/不够涩`：发送一张 R18 图片（需在配置中启用）。
- `/setucd <秒>`：设置冷却时间，立刻持久化。
- `/setu_help`：显示本帮助。

**当前关键配置:**
- 冷却时间：{cfg.get('cooldown', 10)} 秒（作用范围：{cfg.get('cd_scope', 'user')}）
- 最大并发：{cfg.get('max_concurrency', 10)}
- API 尺寸：{cfg.get('api_size', 'regular')} / 显示尺寸：{cfg.get('display_size', 'small')}
- R18 模式：{cfg.get('r18_mode', 'off')}（群聊放行：{cfg.get('r18_in_group', False)}）
- 排除 AI：{cfg.get('exclude_ai', False)} / 显示信息：{cfg.get('show_image_info', False)}
- LLM 工具：{cfg.get('enable_llm_tool', True)}

更多设置请在 AstrBot 管理面板的插件配置页修改。"""
        yield event.plain_result(help_text)
