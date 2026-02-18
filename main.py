from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .core.cave import *
from .core.user import *

@register("MikuchatApi", "Yuuz12", "可调用MikuChat API", "1.0.0", "https://github.com/Yuuz12/astrbot_plugin_mikuchat_api")

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

    @filter.command("user_upload_check")
    async def user_upload_check(self, event: AstrMessageEvent, qq: int | None = None):
        async for msg in user_upload_check(event, qq):
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