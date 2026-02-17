from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, At

import httpx
from mikuchat.apis import User, UserCheck
from mikuchat.models import UserModel


async def user_get(event: AstrMessageEvent, qq: int):
    async with httpx.AsyncClient() as client:
        user = User(client=client)
        await user.get_user_info(qq=qq)
        data: list[UserModel] | UserModel | None = user.model.user
        if data is None or isinstance(data, list):
            logger.error("用户信息解析出错")
            raise ValueError("用户信息解析出错")
        
        yield event.chain_result(
            [
                Plain(f"{data.qq=}\n"),
                Plain(f"{data.id=}\n"),
                Plain(f"{data.name=}\n"),
                Plain(f"{data.kook_id=}\n"),
                Plain(f"{data.telegram_name=}\n"),
                Plain(f"{data.osu_name=}\n"),
                Plain(f"{data.favorability=}\n"),
                Plain(f"{data.coin=}\n"),
                Plain(f"{data.group=}\n"),
                Plain(f"{data.item=}\n"),
                Plain(f"{data.badge=}\n"),
            ]
        )
    
        logger.info(f"{data.qq=}")
        logger.info(f"{data.id=}")
        logger.info(f"{data.name=}")
        logger.info(f"{data.kook_id=}")
        logger.info(f"{data.telegram_name=}")
        logger.info(f"{data.osu_name=}")
        logger.info(f"{data.favorability=}")
        logger.info(f"{data.coin=}")
        logger.info(f"{data.group=}")
        logger.info(f"{data.item=}")
        logger.info(f"{data.badge=}")

async def user_upload_check(event: AstrMessageEvent, qq: int | None = None):
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
        
        yield event.chain_result(
            [
                At(qq=user_id),
                Image.fromBytes(img)
            ]
        )

async def user_check(event: AstrMessageEvent, qq: int):
        async with httpx.AsyncClient() as client:
            user_check = UserCheck(client=client)

            await user_check.get(qq=qq)
            img: bytes = user_check.raw
            yield event.chain_result(
                [
                    Image.fromBytes(img)
                ]
            )

__all__ = [
    "user_get",
    "user_upload_check",
    "user_check",
]