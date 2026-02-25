from os import getcwd
from pathlib import Path
from typing import Any, Literal, Optional, Union

import jinja2

from playwright.async_api import async_playwright

TEMPLATES_PATH = str(Path(__file__).parent / "templates")

env = jinja2.Environment(
    extensions=["jinja2.ext.loopcontrols"],
    loader=jinja2.FileSystemLoader(TEMPLATES_PATH),
    enable_async=True,
)


async def html_to_pic(
        html: str,
        wait: int = 0,
        template_path: str = f"file://{getcwd()}",
        type: Literal["jpeg", "png"] = "png",
        quality: Union[int, None] = None,
        device_scale_factor: float = 2,
        screenshot_timeout: Optional[float] = 30_000,
        full_page: Optional[bool] = True,
        **kwargs,
):
    """html转图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        html (str): html文本
        wait (int, optional): 等待时间. Defaults to 0.
        template_path (str, optional): 模板路径 如 "file:///path/to/template/"
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰
        **kwargs: 传入 page 的参数

    Returns:
        bytes: 图片, 可直接发送
    """
    # logger.debug(f"html:\n{html}")
    if "file:" not in template_path:
        raise Exception("template_path should be file:///path/to/template")
    
    _ctx = None
    try:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch()
        _ctx = await _browser.new_context(
            device_scale_factor=device_scale_factor,
            **kwargs
        )
        
        page = await _ctx.new_page()
        await page.goto(template_path)
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(wait)
        await page.screenshot(
            full_page=full_page,
            type=type,
            quality=quality,
            timeout=screenshot_timeout,
            path=Path(__file__).parent / "html_render_cache" / "kline.png"
        )
    finally:
        if _ctx is not None:
            await _ctx.close()


async def template_to_pic(
        template_path: str,
        template_name: str,
        templates: dict[Any, Any],
        filters: Optional[dict[str, Any]] = None,
        pages: Optional[dict[Any, Any]] = None,
        wait: int = 0,
        type: Literal["jpeg", "png"] = "png",
        quality: Union[int, None] = None,
        device_scale_factor: float = 2,
        screenshot_timeout: Optional[float] = 30_000,
) -> bytes:
    """使用jinja2模板引擎通过html生成图片

    Args:
        screenshot_timeout (float, optional): 截图超时时间，默认30000ms
        template_path (str): 模板路径
        template_name (str): 模板名
        templates (Dict[Any, Any]): 模板内参数 如: {"name": "abc"}
        filters (Optional[Dict[str, Any]]): 自定义过滤器
        pages (Optional[Dict[Any, Any]]): 网页参数 Defaults to
            {"base_url": f"file://{getcwd()}", "viewport": {"width": 500, "height": 10}}
        wait (int, optional): 网页载入等待时间. Defaults to 0.
        type (Literal["jpeg", "png"]): 图片类型, 默认 png
        quality (int, optional): 图片质量 0-100 当为`png`时无效
        device_scale_factor: 缩放比例,类型为float,值越大越清晰
    Returns:
        bytes: 图片 可直接发送
    """
    if pages is None:
        pages = {
            "viewport": {"width": 500, "height": 10},
            "base_url": f"file://{getcwd()}",
        }

    template_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path),
        enable_async=True,
    )

    if filters:
        for filter_name, filter_func in filters.items():
            template_env.filters[filter_name] = filter_func
            logger.debug(f"Custom filter loaded: {filter_name}")

    template = template_env.get_template(template_name)

    return await html_to_pic(
        template_path=f"file://{template_path}",
        html=await template.render_async(**templates),
        wait=wait,
        type=type,
        quality=quality,
        device_scale_factor=device_scale_factor,
        screenshot_timeout=screenshot_timeout,
        **pages,
    )


__all__ = [
    "template_to_pic"
]