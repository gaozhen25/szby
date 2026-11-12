from ..runtime.collector import MemoryStore, build_public_profile_url, build_safe_creator
from ..runtime.context import source_keyword_var
from ..vendor.user_hash import anonymize_user_id, mask_nickname


class DouyinStoreFactory:
    @staticmethod
    def create_store(): return MemoryStore()


async def update_douyin_aweme(item):
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    aweme_id = item.get("aweme_id")
    author_id = author.get("sec_uid") or author.get("sec_user_id") or author.get("uid")
    is_image = bool(item.get("image_post_info") or item.get("images"))
    await MemoryStore().store_content({
        "aweme_id": aweme_id, "title": item.get("desc", ""),
        "type": "image" if is_image else "video",
        "desc": item.get("desc", ""), "create_time": item.get("create_time"),
        "creator_hash": anonymize_user_id(author_id),
        "nickname": mask_nickname(author.get("nickname")),
        "display_name": str(author.get("nickname") or "").strip()[:100],
        "profile_url": build_public_profile_url("dy", author_id),
        "liked_count": stats.get("digg_count"), "collected_count": stats.get("collect_count"),
        "comment_count": stats.get("comment_count"), "share_count": stats.get("share_count"),
        "aweme_url": f"https://www.douyin.com/{'note' if is_image else 'video'}/{aweme_id}",
        "source_keyword": source_keyword_var.get(),
    })


async def update_dy_aweme_comment(aweme_id, item):
    user = item.get("user") or {}
    await MemoryStore().store_comment({
        "comment_id": item.get("cid"), "aweme_id": aweme_id, "content": item.get("text"),
        "creator_hash": anonymize_user_id(user.get("uid")), "nickname": mask_nickname(user.get("nickname")),
        "like_count": item.get("digg_count", 0),
    })


async def batch_update_dy_aweme_comments(aweme_id, comments):
    for comment in comments or []: await update_dy_aweme_comment(aweme_id, comment)


async def save_creator(user_id, creator):
    if creator:
        raw_creator = creator.get("user") or creator
        await MemoryStore().store_creator(
            build_safe_creator("dy", user_id, raw_creator, raw_data=raw_creator)
        )


async def update_dy_aweme_image(*args, **kwargs): return None
async def update_dy_aweme_video(*args, **kwargs): return None
