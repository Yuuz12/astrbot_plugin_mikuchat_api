from pathlib import Path

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.platform import MessageType
from astrbot.core.platform.message_session import MessageSession
from astrbot.api.star import Context

import random
import time
import threading
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from .mikuchat_html_render import template_to_pic

# 虚拟币交易系统 - 轻量化版本

"""
AstrMessageEvent.unified_msg_origin 格式：
platform_id : message_type : session_id
platform_id : 机器人名字
message_type: astrbot.core.platform MessageType
session_id  : 群号/qq号
"""
WHITELIST_SESSIONS: list[tuple[str, str, str]] = []

# 支持的虚拟币种
COINS = ["PIG", "GENSHIN", "DOGE", "SAKIKO", "WUWA", "SHIRUKU", "KIRINO"]

# 初始价格
INITIAL_PRICES = {
    "PIG": 100.0,
    "GENSHIN": 648.0,
    "DOGE": 5.0,
    "SAKIKO": 2.14,
    "WUWA": 648.0,
    "SHIRUKU": 10.0,
    "KIRINO": 10.0,
}

# 币种波动率基础配置（基于币种特性）
VOLATILITY_BASE = {
    "PIG": 0.03,      # 猪猪币，中低等波动
    "GENSHIN": 0.05,     # 原神币，中波动
    "DOGE": 0.07,    # 山寨币，高波动
    "SAKIKO": 0.10,  # 祥子币，极高波动
    "WUWA": 0.05,     # 鸣朝币，中波动
    "SHIRUKU": 0.02,   # 纨素币，低波动
    "KIRINO": 0.02    # 桐乃币，低波动
}

# 波动率随机波动参数
VOLATILITY_RANDOM_RANGE = 0.005  # 波动率随机波动范围 ±0.5%
VOLATILITY_MIN_RATIO = 0.5       # 波动率最低为基值的50%
VOLATILITY_MAX_RATIO = 1.5       # 波动率最高为基值的150%

# 市场波动参数
UPDATE_INTERVAL = 120  # 2分钟更新一次
TRANSACTION_FEE = 0.01  # 1% 交易手续费

# 随机事件参数
EVENT_TRIGGER_PROBABILITY = 0.15  # 15%概率触发
EVENT_COOLDOWN = 1200  # 事件冷却时间20分钟
last_event_time = 0  # 上次事件时间
INACTIVITY_THRESHOLD = 3600  # 1小时无发言视为不活跃

# 历史记录参数
MAX_HISTORY_SIZE = 720  # 每个币种最大历史记录数

# 动态波动率存储
current_volatility = {coin: base for coin, base in VOLATILITY_BASE.items()}

# 全局市场数据
market_prices = INITIAL_PRICES.copy()
market_history = {coin: [] for coin in COINS}
last_update_time = time.time()

# 用户资产数据
user_assets: Dict[str, Dict] = {}  # {user_id: {coin: amount}}
user_balance: Dict[str, float] = {}  # {user_id: balance}
user_orders: Dict[str, List] = {}  # {user_id: [order1, order2, ...]}

# 群聊活跃度记录 {group_umo: last_message_timestamp}
group_last_activity: dict[str, float] = {}

# 后台定时更新控制
market_update_thread = None
market_update_running = False
market_update_lock = threading.Lock()

# 插件上下文（用于调用LLM和发送消息）
_plugin_context: Optional[Context] = None


def market_update_worker():
    """市场更新工作线程"""
    global market_update_running
    
    while market_update_running:
        try:
            # 等待更新间隔
            time.sleep(UPDATE_INTERVAL)
            
            # 执行市场更新
            with market_update_lock:
                update_volatility()
                update_market_prices()
                
            logger.info(f"[Market] 自动更新完成 - 时间: {datetime.now().strftime('%H:%M:%S')}")
            
            # 尝试触发随机事件
            try_trigger_random_event()
            
        except Exception as e:
            logger.error(f"[Market] 自动更新出错: {e}")
            time.sleep(10)  # 出错后等待10秒再重试


def update_group_activity(group_umo: str):
    """更新群聊活跃度记录
    
    Args:
        group_umo: 群聊UMO标识
    """
    global group_last_activity
    group_last_activity[group_umo] = time.time()
    logger.debug(f"[Activity] 更新群聊活跃度: {group_umo}")


def _has_active_groups() -> bool:
    """检查是否有活跃的白名单群聊
    
    Returns:
        True: 至少有一个群聊在1小时内有发言
        False: 所有群聊都超过1小时无发言
    """
    global WHITELIST_SESSIONS, group_last_activity, INACTIVITY_THRESHOLD
    
    if not WHITELIST_SESSIONS:
        return False
    
    current_time = time.time()
    active_groups = []
    inactive_groups = []
    
    for (platform_id, message_type, session_id) in WHITELIST_SESSIONS:
        umo: MessageSession = MessageSession(platform_id, MessageType(message_type), session_id)
        last_activity = group_last_activity.get(str(umo), 0)
        time_since_last = current_time - last_activity
        
        if time_since_last < INACTIVITY_THRESHOLD:
            active_groups.append(str(umo))
            logger.debug(f"[Activity] 群聊活跃: {umo}, 上次发言: {time_since_last:.0f}秒前")
        else:
            inactive_groups.append(str(umo))
            logger.debug(f"[Activity] 群聊不活跃: {umo}, 上次发言: {time_since_last:.0f}秒前")
    
    if active_groups:
        logger.info(f"[Event] 发现 {len(active_groups)} 个活跃群聊，可以触发事件")
        return True
    else:
        logger.info(f"[Event] 所有白名单群聊都超过1小时无发言，跳过触发")
        return False


def try_trigger_random_event():
    """尝试触发随机事件"""
    global last_event_time
    
    current_time = time.time()
    
    # 检查冷却时间
    if current_time - last_event_time < EVENT_COOLDOWN:
        return
    
    # 检查是否有活跃群聊
    if not _has_active_groups():
        return
    
    # 15%概率触发
    if random.random() >= EVENT_TRIGGER_PROBABILITY:
        logger.info("[Event] 本次未触发随机事件")
        return
    
    # 更新上次事件时间
    last_event_time = current_time
    
    # 在独立线程中执行事件（避免阻塞市场更新）
    event_thread = threading.Thread(target=_generate_and_apply_event, daemon=True)
    event_thread.start()
    logger.info("[Event] 触发随机事件，正在生成...")


def _generate_and_apply_event():
    """生成并应用随机事件（在独立线程中运行）"""
    try:
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 随机选择币种和事件类型
        target_coin = random.choice(COINS)
        is_positive = random.choice([True, False])  # True=利好, False=利空
        
        # 执行价格变动（5%-20%涨跌幅）
        change_percent = random.uniform(0.05, 0.20) * (1 if is_positive else -1)
        
        # 运行异步事件生成
        event_message = loop.run_until_complete(
            _generate_event_with_llm(target_coin, change_percent)
        )
        
        if event_message:
            logger.info(f"[Event] 随机事件: {event_message[:50]}...")
            # 发送事件到白名单群聊
            loop.run_until_complete(_send_event_to_groups(event_message))
        
        loop.close()
    except Exception as e:
        logger.error(f"[Event] 生成随机事件出错: {e}")


async def _generate_event_with_llm(coin: str, change_percent: float) -> str:
    """使用LLM生成随机事件并应用价格变动"""
    global _plugin_context
    
    if not _plugin_context:
        logger.warning("[Event] 插件Context未设置，无法调用LLM")
        return _apply_event_fallback(coin, change_percent)
    
    try:
        # 判断是利好还是利空
        is_positive = change_percent > 0
        change_str = f"+{change_percent*100:.1f}%" if is_positive else f"{change_percent*100:.1f}%"
        
        # 构建提示词
        system_prompt = f"""你是一个虚拟币市场新闻生成器。请为{coin}币生成一条突发新闻，解释为什么它刚刚{'暴涨' if is_positive else '暴跌'}了{abs(change_percent)*100:.1f}%。

要求：
1. 内容要简短有趣（50字以内），适合在群聊中播报
2. 可以是荒诞搞笑的新闻（如：创始人被猪拱了、狗狗学会炒币了等）
3. 要提到{coin}币名称和具体涨跌幅
4. 语气要像突发新闻播报

示例：
- "突发！PIG币创始人被发现在农场和猪跳舞，市场信心大增，价格暴涨15%！"
- "DOGE币因马斯克发推'汪汪'而暴涨12%，分析师称这是'狗屎运'！"
- "SAKIKO币因祥子破产传闻暴跌18%，投资者纷纷表示'这是命运'。"
"""
        
        user_prompt = f"请为{coin}币生成一条{'暴涨' if is_positive else '暴跌'}{abs(change_percent)*100:.1f}%的突发新闻："
        
        # 调用LLM
        llm_response = await _call_llm_simple(system_prompt, user_prompt)
        
        if llm_response:
            # 应用价格变动
            _apply_price_change(coin, change_percent)
            
            # 添加价格变动信息
            arrow = "📈" if is_positive else "📉"
            old_price = market_prices[coin] / (1 + change_percent)
            new_price = market_prices[coin]
            return f"📰 【虚拟币快讯】{arrow}\n{llm_response.strip()}\n\n{coin}: {old_price:.2f} → {new_price:.2f} ({change_str})"
        else:
            return _apply_event_fallback(coin, change_percent)
            
    except Exception as e:
        logger.error(f"[Event] LLM调用失败: {e}")
        return _apply_event_fallback(coin, change_percent)


async def _call_llm_simple(system_prompt: str, user_prompt: str) -> str:
    """简单调用LLM"""
    global _plugin_context
    
    try:
        if not _plugin_context:
            logger.warning("[Event] 插件Context未设置")
            return ""
        
        # 使用默认UMO获取provider
        umo = "_default_"
        provider_id = await _plugin_context.get_current_chat_provider_id(umo=umo)
        
        if not provider_id:
            logger.warning("[Event] 未找到可用的LLM provider")
            return ""
        
        # 调用LLM
        llm_resp = await _plugin_context.llm_generate(
            chat_provider_id=provider_id,
            prompt=f"{system_prompt}\n\n{user_prompt}",
        )
        
        if llm_resp and llm_resp.completion_text:
            return llm_resp.completion_text
        return ""
        
    except Exception as e:
        logger.error(f"[Event] LLM调用异常: {e}")
        return ""


def _apply_price_change(coin: str, change_percent: float):
    """应用价格变动"""
    global market_prices, market_history
    
    with market_update_lock:
        old_price = market_prices[coin]
        new_price = old_price * (1 + change_percent)
        market_prices[coin] = max(0.01, new_price)
        
        # 记录价格历史
        market_history[coin].append({
            'timestamp': datetime.now(),
            'price': market_prices[coin],
            'change_percent': change_percent,
            'volatility': current_volatility[coin],
            'event_triggered': True
        })
        if len(market_history[coin]) > MAX_HISTORY_SIZE:
            market_history[coin] = market_history[coin][-MAX_HISTORY_SIZE:]
        
        logger.info(f"[Event] {coin}价格变动: {old_price:.2f} → {market_prices[coin]:.2f} ({change_percent*100:+.1f}%)")


def _apply_event_fallback(coin: str, change_percent: float) -> str:
    """备用事件（当LLM不可用时）"""
    is_positive = change_percent > 0
    change_str = f"+{change_percent*100:.1f}%" if is_positive else f"{change_percent*100:.1f}%"
    arrow = "📈" if is_positive else "📉"
    
    # 应用价格变动
    _apply_price_change(coin, change_percent)
    
    # 利好事件模板
    positive_events = [
        "突发！{coin}币创始人被发现在农场和动物跳舞，市场信心大增！",
        "{coin}币因某大佬在推特上发了相关表情包而暴涨，网友称这是'玄学力量'！",
        "{coin}币社区宣布'上月球'计划，投资者疯狂买入！",
        "某知名交易所宣布上线{coin}币，引发抢购热潮！",
    ]
    
    # 利空事件模板
    negative_events = [
        "突发！{coin}币创始人被传跑路，投资者恐慌抛售！",
        "{coin}币因某大佬在推特上发了'不看好'而暴跌，市场信心受挫！",
        "{coin}币交易所遭遇技术故障，用户无法提现引发恐慌！",
        "某国宣布禁止{coin}币交易，市场一片哀嚎！",
    ]
    
    # 根据涨跌选择事件模板
    if is_positive:
        event_text = random.choice(positive_events).format(coin=coin)
    else:
        event_text = random.choice(negative_events).format(coin=coin)
    
    old_price = market_prices[coin] / (1 + change_percent)
    new_price = market_prices[coin]
    return f"📰 【虚拟币快讯】{arrow}\n{event_text}\n\n{coin}: {old_price:.2f} → {new_price:.2f} ({change_str})"


def _get_active_groups() -> List[str]:
    """获取当前活跃的群聊列表
    
    Returns:
        1小时内有发言的群聊UMO列表
    """
    global WHITELIST_SESSIONS, group_last_activity, INACTIVITY_THRESHOLD
    
    current_time = time.time()
    active_groups = []
    
    for (platform_id, message_type, session_id) in WHITELIST_SESSIONS:
        umo: MessageSession = MessageSession(platform_id, MessageType(message_type), session_id)
        
        last_activity = group_last_activity.get(str(umo), 0)
        if current_time - last_activity < INACTIVITY_THRESHOLD:
            active_groups.append(str(umo))
    
    return active_groups


async def _send_event_to_groups(message: str):
    """发送事件消息到活跃的白名单群聊"""
    global _plugin_context, WHITELIST_SESSIONS
    
    if not _plugin_context:
        logger.warning("[Event] 插件Context未设置，无法发送消息")
        return
    
    if not WHITELIST_SESSIONS:
        logger.info("[Event] 白名单群聊为空，跳过发送")
        return
    
    # 获取活跃群聊
    active_groups = _get_active_groups()
    if not active_groups:
        logger.info("[Event] 没有活跃群聊，跳过发送")
        return
    
    try:
        from astrbot.api.event import MessageChain
        
        # 构建消息链
        message_chain = MessageChain().message(message)
        
        # 发送到每个活跃群聊
        for group_umo in active_groups:
            try:
                await _plugin_context.send_message(group_umo, message_chain)
                logger.info(f"[Event] 事件已发送到活跃群聊: {group_umo}")
            except Exception as e:
                logger.warning(f"[Event] 发送事件到群聊 {group_umo} 失败: {e}")
                
    except Exception as e:
        logger.error(f"[Event] 发送事件消息失败: {e}")


def set_whitelist_groups(sessions: list[tuple[str, str, str]]):
    """设置白名单群聊列表
    
    Args:
        sessions: 群聊UMO列表，格式: [(platform_id, message_type, session_id), ...]
    """
    global WHITELIST_SESSIONS
    WHITELIST_SESSIONS = sessions
    logger.info(f"[Event] 白名单群聊已设置: {WHITELIST_SESSIONS=}")


def get_whitelist_groups() -> list[tuple[str, str, str]]:
    """获取当前白名单群聊列表
    
    Returns:
        当前的白名单群聊列表
    """
    global WHITELIST_SESSIONS
    return WHITELIST_SESSIONS


def set_plugin_context(context: Context):
    """设置插件上下文"""
    global _plugin_context
    _plugin_context = context
    logger.info("[Event] 插件上下文已设置")


def bi_start_market_updates():
    """启动市场自动更新"""
    global market_update_thread, market_update_running
    
    with market_update_lock:
        if market_update_running:
            return  # 已经在运行
        
        market_update_running = True
        market_update_thread = threading.Thread(target=market_update_worker, daemon=True)
        market_update_thread.start()
        logger.info("[Market] 市场自动更新已启动")


def bi_stop_market_updates():
    """停止市场自动更新"""
    global market_update_running
    
    with market_update_lock:
        market_update_running = False
        logger.info("[Market] 市场自动更新已停止")


def init_user(user_id: str):
    """初始化用户账户"""
    if user_id not in user_assets:
        user_assets[user_id] = {coin: 0.0 for coin in COINS}
    if user_id not in user_balance:
        user_balance[user_id] = 10000.0  # 初始资金10000
    if user_id not in user_orders:
        user_orders[user_id] = []


def update_volatility():
    """更新动态波动率（小幅度随机波动）"""
    global current_volatility
    
    for coin in COINS:
        base_volatility = VOLATILITY_BASE.get(coin, 0.02)
        
        # 在基础波动率上添加小幅度随机波动
        random_change = random.uniform(-VOLATILITY_RANDOM_RANGE, VOLATILITY_RANDOM_RANGE)
        new_volatility = current_volatility[coin] + random_change
        
        # 设置波动率保底（在基值的50%-150%范围内）
        min_volatility = base_volatility * VOLATILITY_MIN_RATIO
        max_volatility = base_volatility * VOLATILITY_MAX_RATIO
        
        # 确保波动率在合理范围内
        current_volatility[coin] = max(min_volatility, min(new_volatility, max_volatility))


def update_market_prices():
    """更新市场价格（使用动态波动率）"""
    global market_prices, last_update_time
    
    # 移除时间检查，由后台线程控制频率
    
    for coin in COINS:
        # 获取该币种的动态波动率
        coin_volatility = current_volatility[coin]
        
        # 随机价格波动（基于动态波动率）
        change_percent = random.uniform(-coin_volatility, coin_volatility)
        new_price = market_prices[coin] * (1 + change_percent)
        market_prices[coin] = max(0.01, new_price)  # 防止价格归零
        
        # 记录价格历史
        market_history[coin].append({
            'timestamp': datetime.now(),
            'price': market_prices[coin],
            'change_percent': change_percent,
            'volatility': coin_volatility  # 记录当前波动率
        })
        if len(market_history[coin]) > MAX_HISTORY_SIZE:
            market_history[coin] = market_history[coin][-MAX_HISTORY_SIZE:]
    
    last_update_time = time.time()


def get_coin_price(coin: str) -> float:
    """获取币种当前价格"""
    # 不再主动更新价格，由后台线程负责
    return market_prices.get(coin.upper(), 0.0)


def get_user_total_assets(user_id: str) -> float:
    """计算用户总资产"""
    init_user(user_id)
    total = user_balance[user_id]
    for coin, amount in user_assets[user_id].items():
        total += amount * get_coin_price(coin)
    return total


async def bi_price(event: AstrMessageEvent, coin: str = ""):
    """查看虚拟币价格"""
    # 不再主动更新价格，由后台线程负责
    
    if coin:
        coin = coin.upper()
        if coin not in COINS:
            yield event.plain_result(f"❌ 不支持的币种: {coin}\n支持币种: {', '.join(COINS)}")
            return
        
        price = get_coin_price(coin)
        result = f"💰 {coin} 当前价格\n"
        result += f"━━━━━━━━━━━━━━\n"
        result += f"📈 价格: {price:.2f}\n"
        yield event.plain_result(result)
    else:
        result = "💰 虚拟币市场价格\n"
        result += "━━━━━━━━━━━━━━\n"
        for coin in COINS:
            price = get_coin_price(coin)
            result += f"{coin}: {price:.2f}\n"
        yield event.plain_result(result)


async def bi_buy(event: AstrMessageEvent, coin: str, amount: float, price: float = 0.0):
    """买入虚拟币"""
    user_id = str(event.get_sender_id())
    init_user(user_id)
    
    coin = coin.upper()
    if coin not in COINS:
        yield event.plain_result(f"❌ 不支持的币种: {coin}")
        return
    
    current_price = get_coin_price(coin)
    
    # 市价单
    if price == 0.0:
        price = current_price
    
    total_cost = amount * price
    fee = total_cost * TRANSACTION_FEE  # 计算手续费
    total_with_fee = total_cost + fee
    
    if user_balance[user_id] < total_with_fee:
        yield event.plain_result(f"❌ 余额不足！需要 {total_with_fee:.2f}（含手续费 {fee:.2f}），当前余额: {user_balance[user_id]:.2f}")
        return
    
    # 执行交易（扣除手续费）
    user_balance[user_id] -= total_with_fee
    user_assets[user_id][coin] += amount
    
    result = f"✅ 买入成功！\n"
    result += f"━━━━━━━━━━━━━━\n"
    result += f"币种: {coin}\n"
    result += f"数量: {amount:.2f}\n"
    result += f"价格: {price:.2f}\n"
    result += f"交易额: {total_cost:.2f}\n"
    result += f"手续费: {fee:.2f} ({TRANSACTION_FEE*100:.1f}%)\n"
    result += f"总支出: {total_with_fee:.2f}\n"
    result += f"余额: {user_balance[user_id]:.2f}"
    
    yield event.plain_result(result)


async def bi_sell(event: AstrMessageEvent, coin: str, amount: float, price: float = 0.0):
    """卖出虚拟币"""
    user_id = str(event.get_sender_id())
    init_user(user_id)
    
    coin = coin.upper()
    if coin not in COINS:
        yield event.plain_result(f"❌ 不支持的币种: {coin}")
        return
    
    if user_assets[user_id][coin] < amount:
        yield event.plain_result(f"❌ {coin} 持有量不足！当前持有: {user_assets[user_id][coin]:.2f}")
        return
    
    current_price = get_coin_price(coin)
    
    # 市价单
    if price == 0.0:
        price = current_price
    
    total_income = amount * price
    fee = total_income * TRANSACTION_FEE  # 计算手续费
    net_income = total_income - fee
    
    # 执行交易（扣除手续费）
    user_assets[user_id][coin] -= amount
    user_balance[user_id] += net_income
    
    result = f"✅ 卖出成功！\n"
    result += f"━━━━━━━━━━━━━━\n"
    result += f"币种: {coin}\n"
    result += f"数量: {amount:.2f}\n"
    result += f"价格: {price:.2f}\n"
    result += f"交易额: {total_income:.2f}\n"
    result += f"手续费: {fee:.2f} ({TRANSACTION_FEE*100:.1f}%)\n"
    result += f"净收入: {net_income:.2f}\n"
    result += f"余额: {user_balance[user_id]:.2f}"
    
    yield event.plain_result(result)


async def bi_assets(event: AstrMessageEvent):
    """查看用户资产"""
    user_id = str(event.get_sender_id())
    init_user(user_id)
    
    total_assets = get_user_total_assets(user_id)
    
    result = f"💼 您的资产总览\n"
    result += f"━━━━━━━━━━━━━━\n"
    result += f"💰 现金余额: {user_balance[user_id]:.2f}\n"
    result += f"📊 总资产: {total_assets:.2f}\n\n"
    
    result += f"🪙 虚拟币持仓:\n"
    has_holdings = False
    for coin in COINS:
        amount = user_assets[user_id][coin]
        if amount > 0:
            price = get_coin_price(coin)
            value = amount * price
            result += f"• {coin}: {amount:.2f} 枚 (价值: {value:.2f})\n"
            has_holdings = True
    
    if not has_holdings:
        result += "暂无持仓\n"
    
    yield event.plain_result(result)


async def bi_coins(event: AstrMessageEvent):
    """查看支持币种"""
    result = f"🪙 支持的虚拟币种\n"
    result += f"━━━━━━━━━━━━━━\n"
    for coin in COINS:
        price = get_coin_price(coin)
        result += f"• {coin}: {price:.2f}\n"
    
    yield event.plain_result(result)


async def bi_history(self, event: AstrMessageEvent, coin: str, limit: int = 25):
    """查询指定币种历史价格（K线图表图片）"""
    coin = coin.upper()
    if coin not in COINS:
        yield event.plain_result(f"❌ 不支持的币种: {coin}\n支持币种: {', '.join(COINS)}")
        return
    
    if limit <= 0 or limit > 25:
        yield event.plain_result("❌ 查询数量必须在1-25之间")
        return
    
    history_data = market_history.get(coin, [])
    if not history_data:
        yield event.plain_result(f"❌ {coin} 暂无历史价格数据")
        return
    
    # 获取最近的历史记录
    recent_history = history_data[-limit:]
    current_price = get_coin_price(coin)
    
    # 计算真实的K线数据 (OHLC: Open, High, Low, Close)
    kline_data = []
    
    if len(recent_history) > 0:
        # 第一步：先计算所有K线的OHLC数据
        raw_klines = []
        all_prices = []  # 收集所有价格用于确定显示范围
        
        for i, record in enumerate(recent_history):
            close_price = record['price']
            
            # 计算开盘价（使用前一个收盘价，第一个使用当前价格）
            if i == 0:
                open_price = close_price
            else:
                open_price = recent_history[i-1]['price']
            
            # 根据涨跌幅计算最高最低价（模拟真实K线）
            change = close_price - open_price
            volatility = record.get('volatility', 0.02)
            
            # 计算影线长度（限制在合理范围内，最大为实体高度的50%）
            body_height_price = abs(close_price - open_price)
            max_wick_length = max(body_height_price * 0.5, open_price * volatility * 0.1)
            
            # 最高价和最低价基于实体上下波动
            if change >= 0:  # 上涨
                high_price = close_price + random.uniform(0, max_wick_length)
                low_price = open_price - random.uniform(0, max_wick_length)
            else:  # 下跌
                high_price = open_price + random.uniform(0, max_wick_length)
                low_price = close_price - random.uniform(0, max_wick_length)
            
            # 确保高低价包含开收盘价，且价格在合理范围内
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            # 确保价格不为负
            low_price = max(0.01, low_price)
            
            # 判断涨跌
            is_up = close_price >= open_price
            
            # 收集所有价格点
            all_prices.extend([open_price, high_price, low_price, close_price])
            
            raw_klines.append({
                'time': record['timestamp'].strftime('%H:%M'),
                'open_price': open_price,
                'close_price': close_price,
                'high_price': high_price,
                'low_price': low_price,
                'is_up': is_up
            })
        
        # 第二步：计算显示范围（基于所有高低价）
        max_price = max(all_prices)
        min_price = min(all_prices)
        price_range = max_price - min_price
        
        # 图表尺寸配置
        chart_height = 280  # 图表总高度
        
        # 扩大纵坐标范围，留出上下边距，确保K线能完整显示
        padding_ratio = 0.10  # 上下各留10%的边距
        display_min = min_price - price_range * padding_ratio
        display_max = max_price + price_range * padding_ratio
        display_range = display_max - display_min
        
        # 确保显示范围不为零
        if display_range <= 0:
            display_range = max_price * 0.1
            display_min = min_price - display_range / 2
            display_max = max_price + display_range / 2
        
        # 第三步：计算像素位置并生成最终数据
        for kline in raw_klines:
            open_price = kline['open_price']
            close_price = kline['close_price']
            high_price = kline['high_price']
            low_price = kline['low_price']
            is_up = kline['is_up']
            
            # 计算在图表中的位置（使用扩大后的显示范围）
            # 注意：Y轴向下为正，所以高价对应较小的Y值（在上方）
            if display_range > 0:
                # 计算价格相对于显示范围的比例（0-1）
                high_ratio = (high_price - display_min) / display_range
                low_ratio = (low_price - display_min) / display_range
                open_ratio = (open_price - display_min) / display_range
                close_ratio = (close_price - display_min) / display_range
                
                # 转换为像素位置（从顶部开始，高价在上方=小Y值）
                # 1 - ratio 是因为高价应该在上方（Y值小）
                high_px = int((1 - high_ratio) * chart_height)
                low_px = int((1 - low_ratio) * chart_height)
                open_px = int((1 - open_ratio) * chart_height)
                close_px = int((1 - close_ratio) * chart_height)
            else:
                high_px = low_px = open_px = close_px = chart_height // 2
            
            # 确定各部分的像素位置
            top_px = high_px  # 最高点（Y值较小）
            bottom_px = low_px  # 最低点（Y值较大）
            body_top_px = min(open_px, close_px)  # 实体顶部（较小的Y值）
            body_bottom_px = max(open_px, close_px)  # 实体底部（较大的Y值）
            
            # 计算影线高度
            wick_top_height = body_top_px - top_px  # 上影线高度
            wick_bottom_height = bottom_px - body_bottom_px  # 下影线高度
            
            # 计算实体高度（至少4px）
            body_height = max(4, body_bottom_px - body_top_px)
            
            # 计算K线柱在kline-item中的偏移量（相对于kline-item顶部）
            # 由于kline-item高度=chart_height，所以直接使用top_px
            candle_offset = top_px
            
            kline_data.append({
                'time': kline['time'],
                'open_price': f"{open_price:.2f}",
                'close_price': f"{close_price:.2f}",
                'high_price': f"{high_price:.2f}",
                'low_price': f"{low_price:.2f}",
                'wick_top_height': max(0, wick_top_height),
                'wick_bottom_height': max(0, wick_bottom_height),
                'body_height': body_height,
                'candle_offset': candle_offset,
                'total_height': bottom_px - top_px,
                'is_up': is_up
            })
    
    # 计算统计信息
    if len(recent_history) >= 2:
        first_price = recent_history[0]['price']
        last_price = recent_history[-1]['price']
        total_change = ((last_price - first_price) / first_price) * 100
        total_change_display = total_change
    else:
        total_change = 0
        total_change_display = "N/A"
    
    # 准备模板数据
    template_data = {
        'coin': coin,
        'limit': limit,
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'history_data': kline_data,
        'columns': len(kline_data) if kline_data else 1,
        'current_price': f"{current_price:.2f}",
        'total_change': total_change,
        'total_change_display': f"{total_change_display:+.1f}" if total_change_display != "N/A" else "N/A",
        'max_price': f"{display_max:.2f}",
        'min_price': f"{display_min:.2f}",
        'chart_height': 280
    }
    
    # 使用HTML模板渲染K线图表
    try:
        # 检查是否有html_render方法可用
        if hasattr(self, 'html_render'):
            # url = await self.html_render(tmpl=KLINE_TEMPLATE, data=template_data)
            await template_to_pic(
                template_name="kline_template.jinja2",
                template_path=str(Path(__file__).parent),
                templates=template_data,
            )
            yield event.image_result(url_or_path=str(Path(__file__).parent / "html_render_cache" / "kline.png"))
        else:
            # 如果没有html_render方法，回退到文本显示
            result = f"📈 {coin} 历史价格（最近{len(recent_history)}条）\n"
            result += f"━━━━━━━━━━━━━━\n"
            result += f"当前价格: {current_price:.2f}\n"
            result += f"\n🕒 历史记录:\n"
            
            for i, record in enumerate(recent_history, 1):
                timestamp = record['timestamp'].strftime('%H:%M:%S')
                price = record['price']
                change_percent = record.get('change_percent', 0) * 100
                volatility = record.get('volatility', 0) * 100
                
                change_symbol = "↗️" if change_percent > 0 else "↘️" if change_percent < 0 else "➡️"
                
                result += f"{i}. {timestamp} - {price:.2f} {change_symbol}{abs(change_percent):.1f}% (波动率: {volatility:.1f}%)\n"
            
            if len(recent_history) >= 2:
                result += f"\n📊 统计信息:\n"
                result += f"• 起始价格: {first_price:.2f}\n"
                result += f"• 结束价格: {last_price:.2f}\n"
                result += f"• 总变化: {total_change:+.1f}%\n"
                result += f"• 记录数量: {len(recent_history)}条\n"
            
            result += f"\n💡 提示: 使用 bi_history <币种> [数量] 查询更多历史记录"
            yield event.plain_result(result)
    
    except Exception as e:
        logger.error(f"K线图表渲染失败: {e}")
        yield event.plain_result(f"❌ K线图表生成失败，请稍后重试")


async def bi_volatility(event: AstrMessageEvent):
    """查看币种波动率信息（动态波动率）"""
    # 不再主动更新波动率，由后台线程负责
    
    result = f"📊 币种波动率特性（动态）\n"
    result += f"━━━━━━━━━━━━━━\n"
    
    # 按当前波动率从高到低排序
    sorted_coins = sorted(current_volatility.items(), key=lambda x: x[1], reverse=True)
    
    for coin, current_vol in sorted_coins:
        base_vol = VOLATILITY_BASE[coin]
        current_vol_percent = current_vol * 100
        base_vol_percent = base_vol * 100
        
        # 计算波动率变化
        vol_change = ((current_vol - base_vol) / base_vol) * 100
        change_symbol = "↗️" if vol_change > 0 else "↘️" if vol_change < 0 else "➡️"
        
        if current_vol >= 0.10:
            risk_level = "🔥 极高风险"
        elif current_vol >= 0.07:
            risk_level = "⚠️ 高风险"
        elif current_vol >= 0.03:
            risk_level = "📈 中等风险"
        else:
            risk_level = "🛡️ 低风险"
        
        current_price = get_coin_price(coin)
        result += f"• {coin}: {current_vol_percent:.1f}% {risk_level} {change_symbol}{abs(vol_change):.1f}%\n"
        result += f"  基值: {base_vol_percent:.1f}% | 当前: {current_price:.2f}\n"
    
    result += f"\n💡 动态波动率说明:\n"
    result += f"• 波动率每120秒随机波动 ±0.5%\n"
    result += f"• 波动率保底范围: 基值的50%-200%\n"
    result += f"• 高风险币种可能带来高收益，也可能造成大亏损\n"
    result += f"• 价格每120秒自动更新\n"
    
    yield event.plain_result(result)


async def bi_help(event: AstrMessageEvent):
    """查看所有命令帮助"""
    result = f"📈 虚拟币交易系统帮助\n"
    result += f"━━━━━━━━━━━━━━\n"
    
    result += f"🪙 币种信息命令:\n"
    result += f"• bi_price [币种] - 查看虚拟币价格（不指定币种显示全部）\n"
    result += f"• bi_coins - 查看支持的所有币种列表\n"
    result += f"• bi_volatility - 查看币种波动率特性\n"
    result += f"• bi_history <币种> [数量] - 查询币种历史价格（默认25条，最多25条）\n"
    
    result += f"\n💸 交易命令:\n"
    result += f"• bi_buy <币种> <数量> [价格] - 买入虚拟币（价格可选，默认市价）\n"
    result += f"• bi_sell <币种> <数量> [价格] - 卖出虚拟币（价格可选，默认市价）\n"
    
    result += f"\n👤 账户命令:\n"
    result += f"• bi_assets - 查看您的资产总览（现金+虚拟币持仓）\n"
    result += f"• bi_reset - 重置账户（需要管理员权限）\n"
    
    result += f"\n❓ 帮助命令:\n"
    result += f"• bi_help - 查看此帮助信息\n"
    
    result += f"\n📊 系统特性:\n"
    result += f"• 价格每120秒自动波动一次\n"
    result += f"• 不同币种有差异化波动率（2%-10%）\n"
    result += f"• 交易手续费: 1%\n"
    result += f"• 初始资金: 10000\n"
    result += f"• 支持币种: {', '.join(COINS)}"
    
    yield event.plain_result(result)


async def bi_reset(event: AstrMessageEvent):
    """重置用户账户（需要管理员权限）"""
    user_id = str(event.get_sender_id())
    
    # 简单的管理员检查
    admin_ids = []
    
    if user_id not in admin_ids:
        yield event.plain_result("❌ 权限不足，只有管理员可以重置账户")
        return
    
    # 重置用户数据
    if user_id in user_assets:
        user_assets[user_id] = {coin: 0.0 for coin in COINS}
    if user_id in user_balance:
        user_balance[user_id] = 10000.0
    if user_id in user_orders:
        user_orders[user_id] = []
    
    yield event.plain_result("✅ 用户账户已重置")


__all__ = [
    "bi_price",
    "bi_buy",
    "bi_sell",
    "bi_assets",
    "bi_coins",
    "bi_reset",
    "bi_help",
    "bi_volatility",
    "bi_history",
    "bi_start_market_updates",
    "bi_stop_market_updates",
]

# 模块加载时自动启动市场更新
bi_start_market_updates()