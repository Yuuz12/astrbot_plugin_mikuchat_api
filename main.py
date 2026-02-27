from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.core.platform.message_session import MessageSession

from .core.cave import *
from .core.user import *
from .core.bi import *
from .core.bi import update_group_activity, set_plugin_context, set_whitelist_groups, get_whitelist_groups, save_bi_data, load_bi_data, set_plugin_path

@register("MikuchatApi", "Yuuz12", "可调用MikuChat API", "1.4.3", "https://github.com/Yuuz12/astrbot_plugin_mikuchat_api")

class UserPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("user_get")
    async def user_get(self, event: AstrMessageEvent, qq: int | None = None):
        async for msg in user_get(event, qq):
            yield msg


class UserCheckPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("user_update_check")
    async def user_update_check(self, event: AstrMessageEvent, qq: int | None = None):
        async for msg in user_update_check(event, qq):
            yield msg


class CavePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("cave_get")
    async def cave_get(self, event: AstrMessageEvent):
        async for msg in cave_get(event):
            yield msg

    @filter.command("cave_select")
    async def cave_select(self, event: AstrMessageEvent, id_: int):
        async for msg in cave_select(event, id_):
            yield msg


class BiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 获取插件配置
        self.config = config
        # 设置插件上下文（用于LLM调用）
        set_plugin_context(context)

        # 设置数据文件路径（使用插件名称）
        set_plugin_path(self.name)

        # 加载上次保存的数据
        load_bi_data()

        if 'enabled_bi_groups' not in self.config:
            logger.error("[BiPlugin] 配置项缺少 enabled_bi_groups 键")

        if 'platform_id' not in self.config:
            logger.error("[BiPlugin] 配置项缺少 platform_id 键")

        sessions: list[tuple[str, str, str]] = []
        for group_id in self.config.get('enabled_bi_groups', []):
            if not self.config.get('platform_id', ""):
                break
            sessions.append((self.config.get('platform_id', ""), "GroupMessage", group_id))
        set_whitelist_groups(sessions)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息，更新群聊活跃度"""
        try:
            # 获取消息来源UMO
            umo: MessageSession = MessageSession.from_str(event.unified_msg_origin)
            
            # platform_name = event.get_platform_name()
            # platform_id = event.get_platform_id()
            # session_id = event.get_session_id()
            # self_id = event.get_self_id()
            # logger.info(
            #     f"[BiPlugin] 收到消息来自 {umo} "
            #     f"({platform_name=}, "  # aiocqhttp
            #     f"{platform_id=}, "  # 桐乃酱
            #     f"{session_id=})"   # 群号
            #     f"{self_id=}"       # bot qq号
            # )
            # 
            # logger.info(f"{WHITELIST_SESSIONS=}")
            # logger.info(f"{(umo.platform_name, umo.message_type.value, umo.session_id)=}")
            # logger.info(f"platfrom_id: {self.config['platform_id']}")
            # logger.info(f"config: {self.config['platform_id']}")
            
            # 检查是否是白名单群聊
            if (umo.platform_name, umo.message_type.value, umo.session_id) in get_whitelist_groups():
                # 更新群聊活跃度
                update_group_activity(str(umo))
                logger.info(f"[BiPlugin] 更新群聊活跃度: {umo}")
        except Exception as e:
            logger.info(f"[BiPlugin] 更新群聊活跃度失败: {e}")

    @filter.command("bi_price")
    async def bi_price(self, event: AstrMessageEvent, coin: str = ""):
        async for msg in bi_price(event, coin):
            yield msg

    @filter.command("bi_buy")
    async def bi_buy(self, event: AstrMessageEvent, coin: str, amount: float, price: float = 0.0):
        async for msg in bi_buy(event, coin, amount, price):
            yield msg

    @filter.command("bi_sell")
    async def bi_sell(self, event: AstrMessageEvent, coin: str, amount: float, price: float = 0.0):
        async for msg in bi_sell(event, coin, amount, price):
            yield msg

    @filter.command("bi_assets")
    async def bi_assets(self, event: AstrMessageEvent):
        async for msg in bi_assets(event):
            yield msg

    @filter.command("bi_coins")
    async def bi_coins(self, event: AstrMessageEvent):
        async for msg in bi_coins(event):
            yield msg

    @filter.command("bi_reset")
    async def bi_reset(self, event: AstrMessageEvent):
        async for msg in bi_reset(event):
            yield msg

    @filter.command("bi_help")
    async def bi_help(self, event: AstrMessageEvent):
        async for msg in bi_help(event):
            yield msg

    @filter.command("bi_volatility")
    async def bi_volatility(self, event: AstrMessageEvent):
        async for msg in bi_volatility(event):
            yield msg

    @filter.command("bi_history")
    async def bi_history(self, event: AstrMessageEvent, coin: str, limit: int = 25):
        async for msg in bi_history(self, event, coin, limit):
            yield msg
    
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        bi_stop_market_updates()
        save_bi_data()
