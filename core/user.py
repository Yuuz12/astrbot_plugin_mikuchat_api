from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, Reply

import httpx
from mikuchat.apis import User, UserCheck
from mikuchat.models import UserModel


async def user_get(event: AstrMessageEvent, qq: int | None = None):
    user_id = qq or event.get_sender_id()
    logger.info(f"{user_id=}")
    if not isinstance(user_id, int) and not user_id.isdigit():
        logger.warning("用户ID不是数字")
        raise ValueError("用户ID不是数字")
    
    async with httpx.AsyncClient() as client:
        user = User(client=client)
        await user.get_user_info(qq=int(user_id))
        data: list[UserModel] | UserModel | None = user.model.user
        if data is None or isinstance(data, list):
            logger.error("用户信息解析出错")
            raise ValueError("用户信息解析出错")
        
        yield event.chain_result([
            Plain(
                f"{data.qq=}"
                f"\n{data.id=}"
                f"\n{data.name=}"
                f"\n{data.kook_id=}"
                f"\n{data.telegram_name=}"
                f"\n{data.osu_name=}"
                f"\n{data.favorability=}"
                f"\n{data.coin=}"
                f"\n{data.group=}"
                f"\n{data.item=}"
                f"\n{data.badge=}"
            )
        ])


async def user_update_check(event: AstrMessageEvent, qq: int | None = None):
    user_id = qq or event.get_sender_id()
    logger.info(f"{user_id=}")
    if not isinstance(user_id, int) and not user_id.isdigit():
        logger.warning("用户ID不是数字")
        raise ValueError("用户ID不是数字")
    
    async with httpx.AsyncClient() as client:
        user = User(client=client)
        await user.update_user_check(qq=int(user_id))
        data: list[UserModel] | UserModel | None = user.model.user

        if user.error:
            if user.raw_code == 302:
                logger.info("用户今日已签到")
            else:
                logger.warning("参数错误或账号不存在")
                raise ValueError("参数错误或账号不存在")

        if data is None or isinstance(data, list):
            logger.error("用户签到失败")
            raise ValueError("用户签到失败")
        
        user_check = UserCheck(client=client)
        await user_check.get(qq=int(user_id))
        img: bytes = user_check.raw
        
        yield event.chain_result([
            Reply(id=event.message_obj.message_id),
            Image.fromBytes(img)
        ])

async def user_check(event: AstrMessageEvent, qq: int):
    async with httpx.AsyncClient() as client:
        user_check = UserCheck(client=client)

        await user_check.get(qq=qq)
        img: bytes = user_check.raw
        yield event.chain_result([
            Image.fromBytes(img)
        ])

__all__ = [
    "user_get",
    "user_update_check",
    "user_check",
]