from datetime import date
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.database import create_app_engine
from app.core.security import get_password_hash, verify_password
from app.db.base import Base
from app.db.models import (
    AccountQuotaRecord,
    AccountRecord,
    DashboardRecord,
    MaterialRecord,
    ReportRecord,
    TaskRecord,
    TopicRecord,
    UserRecord,
)


DEMO_ACCOUNTS = [
    ("acc1", "美妆号_01", "专业号", ["小红书"], "美", "美妆测评与教程", "品牌合作", 50),
    ("acc2", "探店号_02", "普通号", ["抖音"], "探", "本地美食探店", "涨粉变现", 10),
    ("acc3", "知识号_03", "专业号", ["视频号"], "知", "知识科普与个人成长", "知识付费", 50),
]

DEMO_TOPICS = {
    "acc1": [
        ("t1", "早八通勤妆5分钟搞定", "热点", "美妆", "video"),
        ("t2", "黄皮显白口红合集推荐", "竞品", "美妆", "image"),
        ("t3", "学生党平价护肤全流程", "趋势", "护肤", "video"),
    ],
    "acc2": [
        ("t1", "本地人强推的苍蝇馆子清单", "热点", "美食", "video"),
        ("t2", "老街区拍照机位全攻略", "竞品", "摄影", "image"),
        ("t3", "新晋网红咖啡馆探店记", "趋势", "探店", "video"),
    ],
    "acc3": [
        ("t1", "高效学习方法论总结", "热点", "教育", "image"),
        ("t2", "职场沟通思维模型", "竞品", "成长", "video"),
        ("t3", "记忆宫殿训练法详解", "趋势", "技巧", "video"),
    ],
}

DEMO_DASHBOARDS = {
    "acc1": ("12.5k", 3, 8, 22, 3, 10, 156),
    "acc2": ("8.2k", 5, 12, 5, 2, 5, 89),
    "acc3": ("20.1k", 1, 15, 35, 3, 6, 234),
}

DEMO_REPORTS = {
    "acc1": (
        "系统会按创作时选择的目标平台筛选同类博主并生成详细竞品分析。",
        "系统会根据目标平台切换对应违禁词规则，目前已纳入小红书、视频号、抖音基础规则。",
        "18-24 岁女性学生及职场新人，偏好平价好物和快速上手教程。",
        "图文种草与反差封面内容更容易获得收藏与搜索流量。",
        "头部博主分析会结合目标平台推荐机制与内容风格生成。",
    ),
    "acc2": (
        "探店内容会按平台偏好切换为强场景展示或熟人分享表达。",
        "重点规避极限词、价格承诺和夸大式体验表达。",
        "20-35 岁城市青年，偏好本地美食、周末出游与情绪价值。",
        "合集视频和路线型图文在本地生活内容中更容易起量。",
        "探店与本地生活头部账号更注重镜头节奏和信任表达。",
    ),
    "acc3": (
        "知识内容按平台不同切换为卡片式图文、口播拆解或高节奏知识短视频。",
        "需重点规避保证效果、绝对提升等知识类夸大表述。",
        "25-35 岁职场人群，偏好高密度、可收藏、可复用的知识内容。",
        "一图看懂、模型拆解、工具应用是高表现内容方向。",
        "头部知识博主更依赖结构化表达和栏目化更新。",
    ),
}

DEMO_TASKS = {
    "acc1": [
        ("k1", "早八通勤妆5分钟搞定", "video", "draft", "10分钟前", "小红书"),
        ("k2", "黄皮显白口红合集", "image", "script", "1小时前", "视频号"),
    ],
    "acc2": [("k1", "本地人强推的苍蝇馆子", "video", "draft", "30分钟前", "抖音")],
    "acc3": [("k1", "高效学习方法论", "image", "draft", "5分钟前", "小红书")],
}

DEMO_MATERIALS = {
    "acc1": [
        ("m1", "早八通勤妆_成品图.png", "image", ["美妆", "成品", "小红书"], "2026-06-11", "T"),
        ("m2", "护肤流程_脚本.txt", "script", ["护肤", "脚本", "视频号"], "2026-06-09", "S"),
    ],
    "acc2": [("m1", "苍蝇馆子探店_成品.mp4", "video", ["探店", "成品", "抖音"], "2026-06-11", "V")],
    "acc3": [("m1", "学习方法论_知识卡片.png", "image", ["教育", "成品", "小红书"], "2026-06-11", "C")],
}


def _upsert_demo_user(session: Session) -> None:
    demo_user = session.get(UserRecord, "u_001")
    if demo_user is None:
        session.add(
            UserRecord(
                id="u_001",
                email="demo@starx.ai",
                password_hash=get_password_hash("demo123"),
                nickname="Demo User",
                status="active",
            )
        )
        return
    if demo_user.password_hash == "demo123" or not demo_user.password_hash.startswith("$2"):
        demo_user.password_hash = get_password_hash("demo123")
    else:
        try:
            verify_password("demo123", demo_user.password_hash)
        except Exception:
            demo_user.password_hash = get_password_hash("demo123")


def _seed_accounts(session: Session) -> None:
    for account_id, name, account_type, platforms, avatar, description, purpose, ai_image_limit in DEMO_ACCOUNTS:
        account = session.get(AccountRecord, account_id)
        if account is None:
            session.add(
                AccountRecord(
                    id=account_id,
                    user_id="u_001",
                    name=name,
                    avatar=avatar,
                    account_type=account_type,
                    platform=platforms[0],
                    platforms=platforms,
                    description=description,
                    purpose=purpose,
                    status="active",
                )
            )
        else:
            account.platform = platforms[0]
            account.platforms = platforms
        existing_quota = (
            session.query(AccountQuotaRecord)
            .filter(AccountQuotaRecord.account_id == account_id, AccountQuotaRecord.quota_date == date.today())
            .first()
        )
        if existing_quota is None:
            session.add(
                AccountQuotaRecord(
                    account_id=account_id,
                    quota_date=date.today(),
                    change_batch_limit=5,
                    change_batch_used=0,
                    change_single_limit=3,
                    change_single_used=0,
                    ai_image_limit=ai_image_limit,
                    ai_image_used=0,
                )
            )


def _seed_workspace(session: Session) -> None:
    for account_id, topics in DEMO_TOPICS.items():
        for topic_id, title, source, category, content_type in topics:
            record_id = f"{account_id}_{topic_id}"
            if session.get(TopicRecord, record_id) is None:
                session.add(
                    TopicRecord(id=record_id, account_id=account_id, title=title, source=source, category=category, content_type=content_type)
                )
    for account_id, values in DEMO_DASHBOARDS.items():
        if session.get(DashboardRecord, account_id) is None:
            session.add(
                DashboardRecord(
                    account_id=account_id,
                    views=values[0],
                    change_count=values[1],
                    creation=values[2],
                    tools=values[3],
                    competitor_count=values[4],
                    competitor_posts=values[5],
                    material_count=values[6],
                )
            )
    for account_id, values in DEMO_REPORTS.items():
        if session.get(ReportRecord, account_id) is None:
            session.add(
                ReportRecord(
                    account_id=account_id,
                    competitors=values[0],
                    prohibited_words=values[1],
                    target_users=values[2],
                    hot_content=values[3],
                    top_bloggers=values[4],
                )
            )
    for account_id, tasks in DEMO_TASKS.items():
        for task_id, title, content_type, status, updated, target_platform in tasks:
            record_id = f"{account_id}_{task_id}"
            if session.get(TaskRecord, record_id) is None:
                session.add(
                    TaskRecord(
                        id=record_id,
                        account_id=account_id,
                        title=title,
                        content_type=content_type,
                        status=status,
                        updated=updated,
                        target_platform=target_platform,
                    )
                )
    for account_id, materials in DEMO_MATERIALS.items():
        for material_id, name, material_type, tags, material_date, thumb in materials:
            record_id = f"{account_id}_{material_id}"
            if session.get(MaterialRecord, record_id) is None:
                session.add(
                    MaterialRecord(
                        id=record_id,
                        account_id=account_id,
                        name=name,
                        material_type=material_type,
                        tags=tags,
                        material_date=material_date,
                        thumb=thumb,
                    )
                )


def init_database(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        _upsert_demo_user(session)
        session.flush()
        _seed_accounts(session)
        session.flush()
        _seed_workspace(session)
        session.commit()


def main() -> None:
    Path("data").mkdir(exist_ok=True)
    engine = create_app_engine()
    init_database(engine)


if __name__ == "__main__":
    main()
