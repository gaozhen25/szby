"""BOSS authentication and messaging endpoints."""

from message_adapter.browser_identity import current_browser_identity


_BROWSER = current_browser_identity()

AUTH_HEALTH_CACHE_TTL_S = 45

BASE_URL = "https://www.zhipin.com"
WEB_BOSS_CHAT_URL = f"{BASE_URL}/web/chat/index"
WEB_BOSS_LOGIN_URL = f"{BASE_URL}/web/user/?ka=header-login"

USER_INFO_URL = "/wapi/zpuser/wap/getUserInfo.json"
GET_WT_URL = "/wapi/zppassport/get/wt"
BOSS_FRIEND_LIST_URL = "/wapi/zprelation/friend/filterByLabel"
BOSS_FRIEND_DETAIL_URL = "/wapi/zprelation/friend/getBossFriendListV2.json"
BOSS_LAST_MSG_URL = "/wapi/zpchat/boss/userLastMsg"
BOSS_HISTORY_MSG_URL = "/wapi/zpchat/boss/historyMsg"
BOSS_EXCHANGE_REQUEST_URL = "/wapi/zpchat/exchange/request"
BOSS_EXCHANGE_ACCEPT_URL = "/wapi/zpchat/exchange/accept"
BOSS_EXCHANGE_CONTENT_URL = "/wapi/zprelation/friend/getExchangeContent"

HEADERS = {
    "User-Agent": _BROWSER.user_agent,
    "sec-ch-ua": _BROWSER.sec_ch_ua,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": _BROWSER.sec_ch_ua_platform,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "DNT": "1",
    "Priority": "u=1, i",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}

SESSION_COOKIES = {"wt2", "zp_at"}
