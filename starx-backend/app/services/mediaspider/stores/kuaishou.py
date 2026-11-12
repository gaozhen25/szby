from ..runtime.collector import MemoryStore, build_public_profile_url, build_safe_creator
from ..runtime.context import source_keyword_var
from ..vendor.user_hash import anonymize_user_id, mask_nickname


class KuaishouStoreFactory:
    @staticmethod
    def create_store(): return MemoryStore()


async def update_kuaishou_video(item):
    photo = item.get("photo") or {}
    author = item.get("author") or {}
    video_id = photo.get("id")
    if not video_id: return
    await MemoryStore().store_content({
        "video_id": video_id, "title": photo.get("caption", "")[:500],
        "type": "video",
        "desc": photo.get("caption", "")[:500], "create_time": photo.get("timestamp"),
        "creator_hash": anonymize_user_id(author.get("id")),
        "nickname": mask_nickname(author.get("name")),
        "display_name": str(author.get("name") or "").strip()[:100],
        "profile_url": build_public_profile_url("ks", author.get("id")),
        "liked_count": photo.get("realLikeCount"), "viewd_count": photo.get("viewCount"),
        "video_url": f"https://www.kuaishou.com/short-video/{video_id}",
        "source_keyword": source_keyword_var.get(),
    })


async def update_ks_video_comment(video_id, item):
    comment_id = item.get("comment_id") or item.get("commentId")
    await MemoryStore().store_comment({
        "comment_id": str(comment_id) if comment_id else None, "video_id": video_id,
        "content": item.get("content"),
        "creator_hash": anonymize_user_id(item.get("author_id") or item.get("authorId")),
        "nickname": mask_nickname(item.get("author_name") or item.get("authorName")),
    })


async def batch_update_ks_video_comments(video_id, comments):
    for comment in comments or []: await update_ks_video_comment(video_id, comment)


async def save_creator(user_id, creator):
    if creator:
        await MemoryStore().store_creator(
            build_safe_creator("ks", user_id, creator, raw_data=creator)
        )
