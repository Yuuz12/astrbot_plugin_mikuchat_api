from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain

import httpx
from mikuchat.apis import Cave
from mikuchat.models import CaveModel


async def cave_get(event: AstrMessageEvent):
    async with httpx.AsyncClient() as client:
        cave = Cave(client=client)
        await cave.get_cave()

        data: CaveModel | None = cave.model.cave
        if data is None:
            logger.error("回声洞解析出错")
            raise ValueError("回声洞解析出错")
        
        logger.info(f"{data.id=}")
        logger.info(f"{data.type=}")
        logger.info(f"{data.qq=}")
        logger.info(f"{data.string=}")
        logger.info(f"{data.image=}")
        logger.info(f"{data.time=}")
        logger.info(f"{data.url=}")

        match data.type:
            case 0:
                if data.string is None:
                    logger.error("文本回声洞解析出错")
                    raise ValueError("文本回声洞解析出错")
                yield event.chain_result([
                    Plain(
                        f"===== 回声洞 {data.id} =====\n{data.string}"
                        f"\n{data.string}"
                    ),
                ])
            case 1:
                if data.string is None:
                    logger.error("图片回声洞解析出错")
                    raise ValueError("图片回声洞解析出错")
                yield event.chain_result([
                    Plain(f"===== 回声洞 {data.id} =====\n"),
                    Image(data.string)
                ])
            case 2:
                if data.string is None or data.image is None:
                    logger.error("图文回声洞解析出错")
                    raise ValueError("图文回声洞解析出错")
                yield event.chain_result([
                    Plain(
                        f"===== 回声洞 {data.id} ====="
                        f"\n{data.string}"
                    ),
                    Image(data.image)
                ])

async def cave_select(event: AstrMessageEvent, id_: int):
    async with httpx.AsyncClient() as client:
        cave = Cave(client=client)
        await cave.select_cave(id=id_)

        data: CaveModel | None = cave.model.cave
        if data is None:
            logger.error("回声洞解析出错")
            raise ValueError("回声洞解析出错")

        match data.type:
            case 0:
                if data.string is None:
                    logger.error("文本回声洞解析出错")
                    raise ValueError("文本回声洞解析出错")
                yield event.plain_result(data.string)
            case 1:
                if data.string is None:
                    logger.error("图片回声洞解析出错")
                    raise ValueError("图片回声洞解析出错")
                yield event.image_result(data.string)
            case 2:
                if data.string is None or data.image is None:
                    logger.error("图文回声洞解析出错")
                    raise ValueError("图文回声洞解析出错")
                yield event.chain_result([
                    Image(data.image),
                    Plain(data.string)
                ])

__all__ = [
    "cave_get",
    "cave_select",
]